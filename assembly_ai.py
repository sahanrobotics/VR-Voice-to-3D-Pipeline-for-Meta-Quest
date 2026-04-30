# assembly_ai.py
import requests
import time
import config

base_url = "https://api.assemblyai.com"
headers = {"authorization": config.ASSEMBLY_API_KEY}


def upload_and_transcribe(filename, update_callback):
    print("\n--- [PHASE 1] ASSEMBLY AI: SPEECH TO TEXT ---")
    update_callback("Uploading audio...")

    with open(filename, "rb") as f:
        response = requests.post(base_url + "/v2/upload", headers=headers, data=f)
    if response.status_code != 200: raise Exception(f"Upload failed: {response.text}")

    audio_url = response.json()["upload_url"]
    print(f"   -> Uploaded URL: {audio_url}")

    update_callback("Transcribing...")
    data = {
        "audio_url": audio_url,
        "speech_models": ["universal-3-pro", "universal-2"],  # Fallback included!
        "language_detection": "en_us",
        "speaker_labels": True
    }

    response = requests.post(base_url + "/v2/transcript", headers=headers, json=data)
    transcript_id = response.json()["id"]
    print(f"   -> Task ID: {transcript_id}")

    while True:
        res = requests.get(f"{base_url}/v2/transcript/{transcript_id}", headers=headers).json()
        status = res.get("status")

        if status == "completed":
            final_text = res['text']
            print(f"   -> ✅ SUCCESS! Transcript: \"{final_text}\"")
            return final_text
        elif status == "error":
            raise Exception(f"Transcription failed: {res.get('error')}")
        else:
            print(f"   -> Polling... Status: {status}")
            time.sleep(3)