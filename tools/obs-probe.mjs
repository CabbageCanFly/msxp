import {OBSClient, cropBox} from "./obs-client.mjs";

const element = id => document.getElementById(id);
const status = message => { element("status").textContent = message; };
let client;
let busy = false;
element("connect-form").addEventListener("submit", async event => {
  event.preventDefault();
  client?.close();
  const password = element("password").value;
  element("password").value = "";
  try {
    client = new OBSClient(Number(element("port").value));
    await client.connect(password);
    const version = await client.request("GetVersion");
    if (!version.availableRequests.includes("GetSourceScreenshot")) throw new Error("GetSourceScreenshot unavailable");
    status(`Connected: OBS ${version.obsVersion}; WebSocket ${version.obsWebSocketVersion}. Capture a game input to test freshness.`);
  } catch (error) { status(error.message); client?.close(); }
});
element("disconnect").onclick = () => { client?.close(); status("Disconnected"); };
element("capture-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  try {
    const roi = element("roi").value.split(",").map(Number);
    cropBox(roi, 1, 1); // validate before requesting an image
    if (!client) throw new Error("Connect first");
    const sourceName = element("source").value;
    const started = performance.now();
    const active = await client.request("GetSourceActive", {sourceName});
    const screenshot = await client.request("GetSourceScreenshot", {sourceName, imageFormat: "png"});
    const image = new Image();
    image.src = screenshot.imageData;
    await image.decode();
    const [x, y, w, h] = cropBox(roi, image.naturalWidth, image.naturalHeight);
    const canvas = element("crop");
    canvas.width = w; canvas.height = h;
    canvas.getContext("2d").drawImage(image, x, y, w, h, 0, 0, w, h);
    const sourceSize = `${image.naturalWidth}x${image.naturalHeight}`;
    const base64Length = screenshot.imageData.length;
    image.src = ""; screenshot.imageData = "";
    const pixels = canvas.getContext("2d").getImageData(0, 0, w, h).data;
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", pixels))].map(b => b.toString(16).padStart(2,"0")).join("");
    status(JSON.stringify({receivedAt: new Date().toISOString(), sourceSize, cropSize: [w,h],
      elapsedMs: Math.round(performance.now() - started), base64Length, active, cropSha256: hash}, null, 2));
    element("download").disabled = false;
  } catch (error) { status(error.message); }
  finally { busy = false; }
});
element("download").onclick = () => element("crop").toBlob(blob => {
  const link = document.createElement("a"), url = URL.createObjectURL(blob);
  link.href = url; link.download = "hud-crop.png"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener("pagehide", () => client?.close());
