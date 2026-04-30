using UnityEngine;
using UnityEngine.InputSystem; 
using WebSocketSharp;
using System.Collections.Concurrent;
using System;
using System.Collections;
using TMPro;
using UnityEngine.UI;

public class VoiceTranscriptionManager : MonoBehaviour
{
    [Header("Network Settings")]
    public string serverAddress = "ws://localhost:8080";
    public float reconnectInterval = 5f; 

    [Header("HUD UI Elements")]
    public GameObject recordingHUD;
    public TextMeshProUGUI mainStatusText;
    public TextMeshProUGUI detailStatusText;
    public Button hudCloseButton;
    public float hudFollowDistance = 1.2f;

    [Header("Audio Settings")]
    public AudioSource audioSource;
    public AudioClip completionSound;
    public AudioClip errorSound; 

    public static event Action<string> OnTranscriptReceived;
    public static event Action<string> OnStatusUpdate;
    public static event Action<string> OnModelReady;

    private WebSocket ws;
    private readonly ConcurrentQueue<string> messageQueue = new ConcurrentQueue<string>();
    
    private bool isRecording = false;
    private bool isGenerating = false;
    private bool manuallyClosed = false;
    private float nextReconnectTime = 0f;

    void Start()
    {
        if (recordingHUD != null) recordingHUD.SetActive(false);
        if (hudCloseButton != null) hudCloseButton.onClick.AddListener(ManualCloseHUD);

        ConnectToServer();
    }

    void Update()
    {
        try 
        {
            HandleNetworkReconnect();
            HandleInput();

            while (messageQueue.TryDequeue(out string message)) 
            { 
                ProcessMessage(message); 
            }

            if (recordingHUD != null && recordingHUD.activeSelf) 
            { 
                UpdateHUDPosition(); 
            }
        }
        catch (Exception e) { Debug.LogError($"[RUNTIME ERROR] {e.Message}"); }
    }

    private void HandleNetworkReconnect()
    {
        if (ws == null || ws.ReadyState == WebSocketState.Closed)
        {
            if (Time.time >= nextReconnectTime)
            {
                nextReconnectTime = Time.time + reconnectInterval;
                ConnectToServer();
            }
        }
    }

    private void ConnectToServer()
    {
        try
        {
            if (ws != null) ws.Close(); 
            ws = new WebSocket(serverAddress);
            ws.OnOpen += (sender, e) => Debug.Log("[NETWORK] ✅ Connected to Python Server!");
            
            // --- FIXED: Inject network errors directly into the UI queue ---
            ws.OnError += (sender, e) => {
                Debug.LogWarning($"[NETWORK] ⚠️ Error: {e.Message}");
                messageQueue.Enqueue("{\"type\": \"error\", \"text\": \"Connection Failed!\"}");
            };
            
            ws.OnClose += (sender, e) => {
                Debug.LogWarning($"[NETWORK] 🔌 Closed: {e.Reason}");
                // Only show the disconnect error if the user is actually waiting for a generation
                if (isGenerating || isRecording || recordingHUD.activeSelf) {
                    messageQueue.Enqueue("{\"type\": \"error\", \"text\": \"Server Disconnected!\"}");
                }
            };
            // ---------------------------------------------------------------

            ws.OnMessage += (sender, e) => {
                if (!string.IsNullOrEmpty(e.Data)) messageQueue.Enqueue(e.Data);
            };
            
            ws.ConnectAsync();
        }
        catch (Exception e) { Debug.LogError($"[NETWORK] Setup Error: {e.Message}"); }
    }

    private void HandleInput()
    {
        bool yButtonPressed = false;
        bool yButtonReleased = false;
        try { 
            yButtonPressed = OVRInput.GetDown(OVRInput.RawButton.Y); 
            yButtonReleased = OVRInput.GetUp(OVRInput.RawButton.Y); 
        } catch { }
        
        bool keyboardPressed = false;
        bool keyboardReleased = false;
        if (Keyboard.current != null) {
            keyboardPressed = Keyboard.current.spaceKey.wasPressedThisFrame;
            keyboardReleased = Keyboard.current.spaceKey.wasReleasedThisFrame;
        }

        if (yButtonPressed || keyboardPressed) StartRecording();
        if (yButtonReleased || keyboardReleased) StopRecording();
    }

    private void StartRecording()
    {
        manuallyClosed = false; 

        if (ws != null && ws.ReadyState == WebSocketState.Open)
        {
            isRecording = true;
            isGenerating = true; 
            ws.Send("{\"action\": \"start\"}");
            UpdateHUDDisplay("LISTENING", "Speak your request...", Color.white);
        }
        else
        {
            // FIXED: Failsafe if user presses button while server is offline
            isGenerating = false;
            isRecording = false;
            UpdateHUDDisplay("ERROR", "Server Offline!", Color.red);
            ForceHideHUDAfterDelay(3f); 
        }
    }

    private void StopRecording()
    {
        if (ws != null && ws.ReadyState == WebSocketState.Open && isRecording)
        {
            isRecording = false;
            ws.Send("{\"action\": \"stop\"}");
            UpdateHUDDisplay("PROCESSING", "Analyzing voice...", Color.white);
        }
        else { isRecording = false; }
    }

    private void ProcessMessage(string jsonMessage)
    {
        try
        {
            var msg = JsonUtility.FromJson<ServerMessage>(jsonMessage);
            if (msg == null) return;
            
            if (msg.type == "transcript") OnTranscriptReceived?.Invoke(msg.text);
            else if (msg.type == "status") ParseStatusMessage(msg.text);
            else if (msg.type == "model_ready") 
            {
                StartCoroutine(HandleModelReadyDelayed(msg.path));
            }
            else if (msg.type == "error")
            {
                // FIXED: Show error in HUD and then forcefully close it
                if (audioSource != null && errorSound != null) audioSource.PlayOneShot(errorSound);
                
                UpdateHUDDisplay("FAILED", msg.text, Color.red);
                ForceHideHUDAfterDelay(4f); // Give user 4 seconds to read error, then hide
            }
        }
        catch { } // Silently ignore bad JSON
    }

    private IEnumerator HandleModelReadyDelayed(string path)
    {
        yield return new WaitForSeconds(2.0f);

        if (audioSource != null && completionSound != null) audioSource.PlayOneShot(completionSound);
        
        OnModelReady?.Invoke(path);

        UpdateHUDDisplay("COMPLETED", "Asset added to inventory.", Color.green);
        ForceHideHUDAfterDelay(3f);
    }

    private void ParseStatusMessage(string rawMessage)
    {
        if (string.IsNullOrEmpty(rawMessage)) return;

        if (rawMessage.Contains("Gemini") || rawMessage.Contains("Groq")) UpdateHUDDisplay("OPTIMIZING", "Refining prompt details...", Color.white);
        else if (rawMessage.Contains("Preview")) UpdateHUDDisplay($"PREVIEW {ExtractPercent(rawMessage)}", "Building 3D shape...", Color.white);
        else if (rawMessage.Contains("Refining")) UpdateHUDDisplay($"TEXTURING {ExtractPercent(rawMessage)}", "Applying wedding textures...", Color.white);
        else if (rawMessage.Contains("Downloading")) UpdateHUDDisplay("DOWNLOADING", "Receiving 3D file...", Color.white);
    }

    private string ExtractPercent(string text) {
        string[] words = text.Split(' ');
        foreach(string word in words) if (word.Contains("%")) return word;
        return "";
    }

    private void UpdateHUDDisplay(string main, string detail, Color textColor)
    {
        if (manuallyClosed) return; 
        
        if (recordingHUD != null) recordingHUD.SetActive(true);
        if (mainStatusText != null) {
            mainStatusText.text = main.ToUpper();
            mainStatusText.color = textColor;
        }
        if (detailStatusText != null) detailStatusText.text = detail;
    }

    public void ManualCloseHUD() { 
        manuallyClosed = true; 
        if (recordingHUD != null) recordingHUD.SetActive(false); 
    }

    // --- GUARANTEED HUD REMOVAL ---
    private void ForceHideHUDAfterDelay(float delaySeconds)
    {
        CancelInvoke(nameof(ForceHideAction));
        isGenerating = false;
        isRecording = false;
        Invoke(nameof(ForceHideAction), delaySeconds);
    }

    private void ForceHideAction()
    {
        if (recordingHUD != null) recordingHUD.SetActive(false);
    }

private void UpdateHUDPosition()
{
    Camera mainCam = Camera.main;
    if (mainCam == null) return; 

    Transform cam = mainCam.transform;

    //Bottom-center offset
    Vector3 offset = (cam.up * -0.55f);   // push DOWN from center

    Vector3 targetPos = cam.position 
                      + (cam.forward * hudFollowDistance) 
                      + offset;

    recordingHUD.transform.position = Vector3.Lerp(
        recordingHUD.transform.position,
        targetPos,
        Time.deltaTime * 5f
    );

    // Face camera properly
    recordingHUD.transform.LookAt(cam);
    recordingHUD.transform.Rotate(0, 180, 0);
}
    private void OnDestroy() { 
        if (ws != null) {
            ws.Close(); 
            ws = null;
        }
    }
}

[System.Serializable]
public class ServerMessage { public string type; public string text; public string path; }