# groq_prompt.py
from groq import Groq
import config


def enhance_prompt(spoken_text):
    print("\n--- [PHASE 2] GROQ AI: PROMPT ENGINEERING ---")
    print(f"   -> Input Voice Text: \"{spoken_text}\"")

    try:
        # Initialize Groq client
        client = Groq(api_key=config.GROQ_API_KEY)

        system_instruction = """
        You are a senior prompt engineer for Meshy AI 3D generation, optimized for Meta Quest VR.

        Convert input into a single comma-separated 3D asset prompt.

        OUTPUT RULES:
        - Output ONLY one comma-separated prompt.
        - No explanations, no extra text, no formatting.
        - Remove filler speech and normalize into structured 3D asset description.

        VR OPTIMIZATION (Meta Quest):
        - Low-poly to mid-poly geometry
        - Clean topology for real-time rendering
        - Prefer baked details over geometry (normal maps, textures)
        - Human-scale proportions suitable for VR interaction
        - Avoid heavy effects (volumetrics, complex transparency, high particle density)

        PBR MATERIALS ONLY:
        - wood, matte plastic, brushed metal, ceramic, fabric, frosted glass (lightweight)
        - No heavy refraction or expensive shader effects

        STYLE:
        - Elegant wedding theme, cinematic lighting, soft baked shadows
        - Realistic but performance-optimized

        ALWAYS END WITH:
        highly optimized for real-time VR (Meta Quest), low poly, PBR materials, baked lighting, game-ready 3D asset, highly detailed appearance without heavy geometry
        """

        # Call the Groq API using Llama 3
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"User Speech: {spoken_text}"}
            ],
            model="llama-3.1-8b-instant",  # Extremely fast and smart model
            temperature=0.7,
        )

        optimized_prompt = chat_completion.choices[0].message.content.strip()
        print(f"   -> ✅ SUCCESS! Enhanced Prompt: \"{optimized_prompt}\"")
        return optimized_prompt

    except Exception as e:
        print(f"   -> ❌ ERROR in Groq: {e}")
        # Stop pipeline if Groq fails
        raise Exception(f"Groq Failed: {e}")