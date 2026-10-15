import {test} from "node:test";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {authentication, cropBox, OBSClient} from "./obs-client.mjs";

test("OBS challenge matches two SHA256/base64 steps", async () => {
  const hash = x => createHash("sha256").update(x).digest("base64");
  assert.equal(await authentication("example", "salt", "challenge"), hash(hash("examplesalt") + "challenge"));
});

test("normalized crop validates and scales", () => {
  assert.deepEqual(cropBox([.25,.5,.75,1], 800,600), [200,300,400,300]);
  assert.throws(() => cropBox([0,0,2,1], 800,600));
  assert.throws(() => new OBSClient(0));
});

test("mock OBS authenticates, correlates response and rejects failed request", async () => {
  const original = globalThis.WebSocket;
  let socket;
  globalThis.WebSocket = class {
    constructor() {
      socket = this; this.sent = [];
      queueMicrotask(() => this.receive({op:0,d:{authentication:{salt:"salt",challenge:"challenge"}}}));
    }
    receive(message) { return this.onmessage({data:JSON.stringify(message)}); }
    send(data) {
      const message = JSON.parse(data); this.sent.push(message);
      if (message.op === 1) queueMicrotask(() => this.receive({op:2,d:{negotiatedRpcVersion:1}}));
    }
    close() { this.onclose?.({code:1000}); }
  };
  try {
    const client = new OBSClient();
    await client.connect("example");
    assert.equal(socket.sent[0].d.eventSubscriptions, 0);
    const response = client.request("GetSourceScreenshot", {sourceName:"game",imageFormat:"png"});
    const requestId = socket.sent.at(-1).d.requestId;
    await socket.receive({op:7,d:{requestId,requestStatus:{result:true},responseData:{imageData:"data:image/png;base64,AA=="}}});
    assert.match((await response).imageData, /^data:image/);
    const failure = client.request("GetSourceActive", {sourceName:"missing"});
    const rejected = assert.rejects(failure, /600/);
    await socket.receive({op:7,d:{requestId:socket.sent.at(-1).d.requestId,requestStatus:{result:false,code:600}}});
    await rejected;
    client.close();
    await assert.rejects(client.request("GetVersion"), /Connect/);
  } finally { globalThis.WebSocket = original; }
});
