import asyncio
import os
import shutil
from playwright.async_api import async_playwright

async def record_demo():
    output_dir = "demo_video"
    os.makedirs(output_dir, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=output_dir,
            record_video_size={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        
        print("1. Navigating to http://localhost:8080/...")
        await page.goto("http://localhost:8080/", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        
        # Prompt 1: What app does best - 1RM & Workload analysis
        prompt1 = "Calculate my 1RM for 80kg x 8 reps and show intensity targets"
        print(f"2. Typing Prompt 1: '{prompt1}'...")
        await page.type("#input", prompt1, delay=50)
        await page.wait_for_timeout(1000)
        await page.click("form button[type='submit']")
        
        print("3. Waiting for Agent response to Prompt 1...")
        # Wait until typing indicator vanishes and response bubble appears
        await page.wait_for_selector(".msg.agent:nth-child(3)", timeout=30000)
        await page.wait_for_timeout(4000)
        
        # Prompt 2: Richer prompt showing Firestore DB lookup + Image Generation
        prompt2 = "Search Chest workout routines in Firestore and generate a fitness image of a chest exercise form guide"
        print(f"4. Typing Prompt 2: '{prompt2}'...")
        await page.type("#input", prompt2, delay=40)
        await page.wait_for_timeout(1000)
        await page.click("form button[type='submit']")
        
        print("5. Waiting for Agent response to Prompt 2 (Firestore DB + Image Gen)...")
        await page.wait_for_selector(".msg.agent:nth-child(5)", timeout=60000)
        await page.wait_for_timeout(5000)
        
        # Scroll smoothly to bottom
        print("6. Scrolling to view full card and generated image...")
        await page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
        await page.wait_for_timeout(4000)
        
        video_path = await page.video.path()
        print(f"Recorded video saved raw to: {video_path}")
        
        await context.close()
        await browser.close()
        
        target_path = "fitpulse_ai_demo.webm"
        shutil.copy(video_path, target_path)
        print(f"✅ Demo video successfully copied to: {target_path}")

if __name__ == "__main__":
    asyncio.run(record_demo())
