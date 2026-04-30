# meshy_generator.py
import requests
import time
import config
import os

headers = {"Authorization": f"Bearer {config.MESHY_API_KEY}"}


def generate_3d_model(prompt, update_callback):
    print("\n--- [PHASE 3] MESHY AI: 3D GENERATION ---")
    print(f"   -> Generating 3D model for: \"{prompt}\"")

    # 1. Preview
    update_callback("Meshy: Creating Preview...")
    res = requests.post("https://api.meshy.ai/openapi/v2/text-to-3d", headers=headers, json={
        "mode": "preview", "prompt": prompt, "should_remesh": True
    })
    res.raise_for_status()
    preview_task_id = res.json()["result"]
    print(f"   -> Preview Task ID: {preview_task_id}")

    while True:
        task = requests.get(f"https://api.meshy.ai/openapi/v2/text-to-3d/{preview_task_id}", headers=headers).json()
        if task["status"] == "SUCCEEDED":
            print(f"   -> ✅ Preview Finished!")
            break
        elif task["status"] in ["FAILED", "EXPIRED"]:
            raise Exception("Meshy Preview Failed.")

        progress = task.get("progress", 0)
        update_callback(f"Meshy: Preview {progress}%")
        print(f"   -> Previewing... {progress}%")
        time.sleep(5)

    # 2. Refine
    update_callback("Meshy: High-Quality Refinement...")
    print(f"   -> Starting Refinement Task...")
    res = requests.post("https://api.meshy.ai/openapi/v2/text-to-3d", headers=headers, json={
        "mode": "refine", "preview_task_id": preview_task_id
    })
    refine_task_id = res.json()["result"]
    print(f"   -> Refine Task ID: {refine_task_id}")

    while True:
        task = requests.get(f"https://api.meshy.ai/openapi/v2/text-to-3d/{refine_task_id}", headers=headers).json()
        if task["status"] == "SUCCEEDED":
            print(f"   -> ✅ Refinement Finished!")
            break
        elif task["status"] in ["FAILED", "EXPIRED"]:
            raise Exception("Meshy Refine Failed.")

        progress = task.get("progress", 0)
        update_callback(f"Meshy: Refining {progress}%")
        print(f"   -> Refining... {progress}%")
        time.sleep(5)

    # 3. Download
    update_callback("Meshy: Downloading...")
    glb_url = task["model_urls"]["glb"]
    print(f"   -> Downloading from: {glb_url}")

    model_response = requests.get(glb_url)

    # Save with a unique name so it doesn't overwrite old models!
    timestamp = int(time.time())
    filename = f"wedding_asset_{timestamp}.glb"
    with open(filename, "wb") as f:
        f.write(model_response.content)

    print(f"   -> ✅ Saved to disk as: {filename}")

    # Get the absolute path so you know exactly where it is on your computer
    absolute_path = os.path.abspath(filename)
    return absolute_path