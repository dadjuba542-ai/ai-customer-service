(function () {
  'use strict';

  const TARGET_SAMPLE_RATE = 16000;
  const PACKET_DURATION_MS = 200;
  const PACKET_BYTES = TARGET_SAMPLE_RATE * 2 * PACKET_DURATION_MS / 1000;

  class TencentRealtimeSpeechController {
    constructor(callbacks = {}) {
      this.callbacks = callbacks;
      this.audioContext = null;
      this.stream = null;
      this.source = null;
      this.processor = null;
      this.silentGain = null;
      this.socket = null;
      this.pendingBytes = new Uint8Array(0);
      this.pcmChunks = [];
      this.pcmBytes = 0;
      this.ready = false;
      this.captureStopped = false;
      this.ended = false;
      this.failed = false;
      this.stopPromise = null;
      this.stopResolve = null;
      this.stopReject = null;
      this.stopTimeout = null;
      this.maxDurationSeconds = 60;
    }

    static isSupported() {
      return !!(
        navigator.mediaDevices &&
        navigator.mediaDevices.getUserMedia &&
        (window.AudioContext || window.webkitAudioContext) &&
        window.WebSocket
      );
    }

    async start(session) {
      if (!TencentRealtimeSpeechController.isSupported()) {
        throw new Error('当前浏览器不支持实时语音输入');
      }
      if (!session || !session.url) throw new Error('实时语音会话无效');

      this.maxDurationSeconds = Number(session.max_duration_seconds) || 60;
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: false,
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      this._emit('onState', 'connecting');

      try {
        await this._openSocket(session.url);
        await this._startAudioPipeline();
      } catch (error) {
        await this.cancel();
        throw error;
      }
      return this;
    }

    async _openSocket(url) {
      await new Promise((resolve, reject) => {
        let settled = false;
        const socket = new WebSocket(url);
        socket.binaryType = 'arraybuffer';
        this.socket = socket;

        const connectTimer = window.setTimeout(() => {
          if (settled) return;
          settled = true;
          reject(new Error('腾讯云实时识别连接超时'));
          socket.close();
        }, 8000);

        socket.onopen = () => {
          if (settled) return;
          settled = true;
          window.clearTimeout(connectTimer);
          resolve();
        };
        socket.onmessage = (event) => this._handleMessage(event.data);
        socket.onerror = () => {
          if (!settled) {
            settled = true;
            window.clearTimeout(connectTimer);
            reject(new Error('无法连接腾讯云实时识别'));
          } else {
            this._fail(new Error('腾讯云实时识别连接异常'));
          }
        };
        socket.onclose = () => {
          window.clearTimeout(connectTimer);
          if (!settled) {
            settled = true;
            reject(new Error('腾讯云实时识别连接已关闭'));
          } else if (!this.ended && !this.failed) {
            this._fail(new Error('腾讯云实时识别连接中断'));
          }
        };
      });
    }

    async _startAudioPipeline() {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioContext = new AudioContextClass();
      if (this.audioContext.state === 'suspended') await this.audioContext.resume();
      this.source = this.audioContext.createMediaStreamSource(this.stream);
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.silentGain = this.audioContext.createGain();
      this.silentGain.gain.value = 0;
      this.processor.onaudioprocess = (event) => this._handleAudio(event.inputBuffer.getChannelData(0));
      this.source.connect(this.processor);
      this.processor.connect(this.silentGain);
      this.silentGain.connect(this.audioContext.destination);
    }

    _handleAudio(samples) {
      if (this.captureStopped || this.failed) return;
      const downsampled = this._downsample(samples, this.audioContext.sampleRate, TARGET_SAMPLE_RATE);
      const pcm = this._floatToPcm16(downsampled);
      if (!pcm.byteLength) return;

      this.pcmChunks.push(pcm.slice());
      this.pcmBytes += pcm.byteLength;
      this._emit('onVolume', this._calculateVolume(samples));
      this._appendPending(pcm);
      this._flushPackets(false);
    }

    _downsample(input, sourceRate, targetRate) {
      if (sourceRate === targetRate) return new Float32Array(input);
      if (sourceRate < targetRate) return new Float32Array(input);
      const ratio = sourceRate / targetRate;
      const outputLength = Math.round(input.length / ratio);
      const output = new Float32Array(outputLength);
      let sourceOffset = 0;
      for (let i = 0; i < outputLength; i += 1) {
        const nextOffset = Math.round((i + 1) * ratio);
        let sum = 0;
        let count = 0;
        for (; sourceOffset < nextOffset && sourceOffset < input.length; sourceOffset += 1) {
          sum += input[sourceOffset];
          count += 1;
        }
        output[i] = count ? sum / count : 0;
      }
      return output;
    }

    _floatToPcm16(input) {
      const buffer = new ArrayBuffer(input.length * 2);
      const view = new DataView(buffer);
      for (let i = 0; i < input.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, input[i]));
        view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      }
      return new Uint8Array(buffer);
    }

    _appendPending(chunk) {
      const merged = new Uint8Array(this.pendingBytes.length + chunk.length);
      merged.set(this.pendingBytes, 0);
      merged.set(chunk, this.pendingBytes.length);
      this.pendingBytes = merged;
    }

    _flushPackets(flushAll) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
      while (this.pendingBytes.length >= PACKET_BYTES) {
        this.socket.send(this.pendingBytes.slice(0, PACKET_BYTES));
        this.pendingBytes = this.pendingBytes.slice(PACKET_BYTES);
      }
      if (flushAll && this.pendingBytes.length) {
        this.socket.send(this.pendingBytes);
        this.pendingBytes = new Uint8Array(0);
      }
    }

    _calculateVolume(samples) {
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / Math.max(1, samples.length));
      return Math.min(1, rms * 5);
    }

    _handleMessage(raw) {
      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        return;
      }
      if (Number(data.code) !== 0) {
        this._fail(new Error(data.message || `腾讯云实时识别错误（${data.code}）`));
        return;
      }
      if (!this.ready) {
        this.ready = true;
        this._emit('onState', 'recording');
      }
      const result = data.result || {};
      const text = String(result.voice_text_str || '');
      if (Number(result.slice_type) === 2) this._emit('onSentenceEnd', text, result);
      else if (text) this._emit('onPartial', text, result);

      if (Number(data.final) === 1) {
        this.ended = true;
        this.captureStopped = true;
        this._stopCapture();
        this._resolveStop(data);
        this._emit('onComplete', data);
        this._cleanup(true);
      }
    }

    stop() {
      if (this.stopPromise) return this.stopPromise;
      this.captureStopped = true;
      this._stopCapture();
      this._flushPackets(true);
      this.stopPromise = new Promise((resolve, reject) => {
        this.stopResolve = resolve;
        this.stopReject = reject;
      });
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'end' }));
        this._emit('onState', 'finalizing');
        this.stopTimeout = window.setTimeout(() => {
          this._fail(new Error('腾讯云实时识别收尾超时'));
        }, 7000);
      } else {
        this._fail(new Error('腾讯云实时识别连接不可用'));
      }
      return this.stopPromise;
    }

    async cancel() {
      this.captureStopped = true;
      this.ended = true;
      this._stopCapture();
      this._cleanup(true);
    }

    getWavBlob() {
      const header = new ArrayBuffer(44);
      const view = new DataView(header);
      const writeString = (offset, value) => {
        for (let i = 0; i < value.length; i += 1) view.setUint8(offset + i, value.charCodeAt(i));
      };
      writeString(0, 'RIFF');
      view.setUint32(4, 36 + this.pcmBytes, true);
      writeString(8, 'WAVE');
      writeString(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, TARGET_SAMPLE_RATE, true);
      view.setUint32(28, TARGET_SAMPLE_RATE * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeString(36, 'data');
      view.setUint32(40, this.pcmBytes, true);
      return new Blob([header, ...this.pcmChunks], { type: 'audio/wav' });
    }

    _stopCapture() {
      if (this.processor) {
        this.processor.onaudioprocess = null;
        try { this.processor.disconnect(); } catch {}
      }
      if (this.source) {
        try { this.source.disconnect(); } catch {}
      }
      if (this.silentGain) {
        try { this.silentGain.disconnect(); } catch {}
      }
      if (this.stream) this.stream.getTracks().forEach((track) => track.stop());
    }

    _resolveStop(data) {
      if (this.stopTimeout) window.clearTimeout(this.stopTimeout);
      this.stopTimeout = null;
      if (this.stopResolve) this.stopResolve(data);
      this.stopResolve = null;
      this.stopReject = null;
    }

    _fail(error) {
      if (this.failed || this.ended) return;
      this.failed = true;
      this.captureStopped = true;
      if (this.stopTimeout) window.clearTimeout(this.stopTimeout);
      this.stopTimeout = null;
      this._stopCapture();
      if (this.stopReject) this.stopReject(error);
      this.stopResolve = null;
      this.stopReject = null;
      this._emit('onError', error);
      this._cleanup(true);
    }

    _cleanup(closeSocket) {
      if (this.audioContext && this.audioContext.state !== 'closed') {
        this.audioContext.close().catch(() => {});
      }
      if (closeSocket && this.socket && this.socket.readyState < WebSocket.CLOSING) {
        this.socket.close();
      }
      this.audioContext = null;
      this.processor = null;
      this.source = null;
      this.silentGain = null;
      this.stream = null;
    }

    _emit(name, ...args) {
      const callback = this.callbacks[name];
      if (typeof callback === 'function') callback(...args);
    }
  }

  window.TencentRealtimeSpeechController = TencentRealtimeSpeechController;
})();
