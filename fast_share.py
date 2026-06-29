import asyncio
import threading
import mss
import cv2  # Requires: pip install opencv-python aiohttp
import numpy as np
from aiohttp import web

# Combined HTML & JavaScript using relative WebSocket paths
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>High-FPS Python Screen Share</title>
    <style>
        body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; height: 100vh; overflow: hidden; font-family: sans-serif;}
        img { max-width: 100%; max-height: 100%; object-fit: contain; }
        #fps { position: absolute; top: 10px; left: 10px; color: #0f0; background: rgba(0,0,0,0.7); padding: 5px 10px; border-radius: 4px; }
    </style>
</head>
<body>
    <div id="fps">FPS: 0</div>
    <img id="screen" src="" alt="Waiting for stream...">
    <script>
        const img = document.getElementById('screen');
        const fpsCounter = document.getElementById('fps');
        let frameCount = 0;
        
        setInterval(() => {
            fpsCounter.innerText = `FPS: ${frameCount}`;
            frameCount = 0;
        }, 1000);

        // Dynamically match protocol and port automatically
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
        ws.binaryType = 'blob';

        ws.onmessage = (event) => {
            const url = URL.createObjectURL(event.data);
            const oldUrl = img.src;
            img.src = url;
            frameCount++;
            if (oldUrl) URL.revokeObjectURL(oldUrl);
        };

        ws.onerror = (err) => console.error("Stream error: ", err);
    </script>
</body>
</html>
"""

current_frame = b""
frame_lock = threading.Lock()

def capture_loop():
    """Background loop dedicated entirely to hyper-fast screen capture and JPEG compression."""
    global current_frame
    with mss.MSS() as sct:
        monitor = sct.monitors[1]
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        
        while True:
            sct_img = sct.grab(monitor)
            img_np = np.frombuffer(sct_img.bgra, dtype=np.uint8).reshape(sct_img.height, sct_img.width, 4)
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
            result, img_bytes = cv2.imencode('.jpg', img_bgr, encode_param)
            
            if result:
                with frame_lock:
                    current_frame = img_bytes.tobytes()

async def handle_index(request):
    """Serves the main web page."""
    return web.Response(text=HTML_PAGE, content_type='text/html')

async def handle_websocket(request):
    """Pushes frames over the WebSocket protocol using a single port."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    global current_frame
    last_sent = b""
    
    try:
        while not ws.closed:
            with frame_lock:
                frame_to_send = current_frame
            
            if frame_to_send and frame_to_send != last_sent:
                await ws.send_bytes(frame_to_send)
                last_sent = frame_to_send
                
            await asyncio.sleep(0.005) # Slightly relaxed to prevent CPU starvation
    except Exception:
        pass
    return ws

def main():
    # Dependencies required: pip install aiohttp opencv-python mss numpy
    threading.Thread(target=capture_loop, daemon=True).start()
    
    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/ws', handle_websocket)
    ])
    
    print("Streaming engine running. Access it via your Tailscale IP on port 8000.")
    web.run_app(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStreaming halted.")
