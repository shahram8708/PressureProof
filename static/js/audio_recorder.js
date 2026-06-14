class AudioRecorder {
    constructor(options = {}) {
        this.chunkInterval = options.chunkInterval || 3000;
        this.onChunk = typeof options.onChunk === "function" ? options.onChunk : () => {};
        this.onStop = typeof options.onStop === "function" ? options.onStop : () => {};
        this.onError = typeof options.onError === "function" ? options.onError : () => {};
        this.onPermissionDenied =
            typeof options.onPermissionDenied === "function"
                ? options.onPermissionDenied
                : () => {};

        this.mediaRecorder = null;
        this.stream = null;
        this.chunks = [];
        this.mimeType = AudioRecorder.getSupportedMimeType();
    }

    static getSupportedMimeType() {
        const mimeTypes = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/ogg;codecs=opus",
            "audio/ogg",
            "audio/mp4",
        ];

        for (const type of mimeTypes) {
            if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }

        return "";
    }

    async start() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            const error = new Error("Audio recording is not supported in this browser.");
            this.onError(error);
            throw error;
        }

        try {
            this.chunks = [];
            this.stream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: false,
            });

            const options = this.mimeType ? { mimeType: this.mimeType } : undefined;
            this.mediaRecorder = new MediaRecorder(this.stream, options);

            this.mediaRecorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    this.chunks.push(event.data);
                    this.onChunk(event.data);
                }
            };

            this.mediaRecorder.onerror = (event) => {
                const error = event.error || new Error("An unknown MediaRecorder error occurred.");
                this.onError(error);
            };

            this.mediaRecorder.onstop = () => {
                const blob = this.getBlob();
                this.onStop(blob);
            };

            this.mediaRecorder.start(this.chunkInterval);
            return Promise.resolve(this.stream);
        } catch (error) {
            if (error && error.name === "NotAllowedError") {
                this.onPermissionDenied(error);
            } else {
                this.onError(new Error(`Unable to start recording: ${error.message}`));
            }
            throw error;
        }
    }

    stop() {
        if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
            this.mediaRecorder.stop();
        }

        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
    }

    getBlob() {
        const type = this.mimeType || "audio/webm";
        return new Blob(this.chunks, { type });
    }
}

window.AudioRecorder = AudioRecorder;
