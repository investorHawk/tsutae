// マイクの音をそのまま（圧縮せず）画面側へ渡す
class CaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      const copy = channel.slice();
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}

registerProcessor("capture", CaptureProcessor);
