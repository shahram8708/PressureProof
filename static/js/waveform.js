class WaveformVisualizer {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        this.options = {
            barCount: Number.isInteger(options.barCount) ? options.barCount : 7,
            barColor: options.barColor || "#F59E0B",
            barWidth: Number.isInteger(options.barWidth) ? options.barWidth : 6,
            barGap: Number.isInteger(options.barGap) ? options.barGap : 4,
            minHeight: Number.isInteger(options.minHeight) ? options.minHeight : 4,
            maxHeight: Number.isInteger(options.maxHeight) ? options.maxHeight : 40,
        };

        this.audioContext = null;
        this.source = null;
        this.analyser = null;
        this.dataArray = null;
        this.animationFrameId = null;

        this.canvas = null;
        this.context = null;
    }

    init(stream) {
        if (!this.container) {
            throw new Error(`Waveform container with id \"${this.containerId}\" was not found.`);
        }

        const ContextClass = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new ContextClass();
        this.source = this.audioContext.createMediaStreamSource(stream);

        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
        this.analyser.smoothingTimeConstant = 0.8;
        this.source.connect(this.analyser);

        this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);

        this._ensureCanvas();
        this.showIdle();
        this.startDrawing();
    }

    _ensureCanvas() {
        const existingCanvas = this.container.querySelector("#waveformCanvas");
        this.canvas = existingCanvas || document.createElement("canvas");

        if (!existingCanvas) {
            this.canvas.id = "waveformCanvas";
            this.container.appendChild(this.canvas);
        }

        const width = this.container.clientWidth || 240;
        const height = Math.max(this.options.maxHeight * 2, 96);
        this.canvas.width = width;
        this.canvas.height = height;
        this.context = this.canvas.getContext("2d");
    }

    _drawRoundedRect(x, y, width, height, radius, opacity = 1) {
        if (!this.context) {
            return;
        }

        const ctx = this.context;
        const r = Math.min(radius, width / 2, height / 2);
        ctx.save();
        ctx.globalAlpha = opacity;
        ctx.fillStyle = this.options.barColor;

        if (typeof ctx.roundRect === "function") {
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, r);
            ctx.fill();
        } else {
            ctx.beginPath();
            ctx.moveTo(x + r, y);
            ctx.lineTo(x + width - r, y);
            ctx.quadraticCurveTo(x + width, y, x + width, y + r);
            ctx.lineTo(x + width, y + height - r);
            ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
            ctx.lineTo(x + r, y + height);
            ctx.quadraticCurveTo(x, y + height, x, y + height - r);
            ctx.lineTo(x, y + r);
            ctx.quadraticCurveTo(x, y, x + r, y);
            ctx.closePath();
            ctx.fill();
        }

        ctx.restore();
    }

    _drawBars(heights, opacity = 1) {
        if (!this.canvas || !this.context) {
            return;
        }

        this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);

        const { barCount, barWidth, barGap } = this.options;
        const totalWidth = barCount * barWidth + (barCount - 1) * barGap;
        let startX = (this.canvas.width - totalWidth) / 2;
        const centerY = this.canvas.height / 2;

        heights.forEach((height) => {
            const y = centerY - height / 2;
            this._drawRoundedRect(startX, y, barWidth, height, barWidth / 2, opacity);
            startX += barWidth + barGap;
        });
    }

    startDrawing() {
        if (!this.analyser || !this.dataArray) {
            return;
        }

        const animate = () => {
            this.animationFrameId = window.requestAnimationFrame(animate);
            this.analyser.getByteFrequencyData(this.dataArray);

            const heights = [];
            for (let index = 0; index < this.options.barCount; index += 1) {
                const frequencyIndex = Math.floor(
                    (index / this.options.barCount) * (this.dataArray.length - 1)
                );
                const normalized = this.dataArray[frequencyIndex] / 255;
                const barHeight =
                    this.options.minHeight +
                    normalized * (this.options.maxHeight - this.options.minHeight);
                heights.push(barHeight);
            }

            this._drawBars(heights, 1);
        };

        animate();
    }

    stop() {
        if (this.animationFrameId) {
            window.cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        this._drawBars(new Array(this.options.barCount).fill(this.options.minHeight), 0.8);

        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }
        if (this.analyser) {
            this.analyser.disconnect();
            this.analyser = null;
        }
    }

    showIdle() {
        this._drawBars(new Array(this.options.barCount).fill(this.options.minHeight), 0.45);
    }
}

window.WaveformVisualizer = WaveformVisualizer;
