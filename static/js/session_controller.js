class SessionController {
    constructor(options = {}) {
        this.sessionCalibration = options.sessionCalibration || {};
        this.audioChunkUrl = options.audioChunkUrl || "";
        this.sessionCompleteUrl = options.sessionCompleteUrl || "";
        this.csrfToken = options.csrfToken || "";
        this.sessionId = Number(options.sessionId || 0);
        this.segmentDuration = Number(options.segmentDuration || 180);
        this.transitionDuration = Number(options.transitionDuration || 10);

        this.recorder = null;
        this.waveform = null;
        this.stream = null;

        this.sessionStartTime = null;
        this.segmentStartTime = null;
        this.currentSegment = 1;
        this.totalSegments = 2;
        this.chunkIndex = 0;
        this.injectionFired = false;
        this.earlyExitTriggered = false;
        this.earlyExitReason = null;

        this.timerInterval = null;
        this.segmentInterval = null;
        this.segmentTransitionTimeout = null;
        this.sessionCompletionTimeout = null;
        this.topicPivotTimeout = null;
        this.distractorInterval = null;
        this.completionPollInterval = null;
        this.completeOverlayProgressInterval = null;
        this.completionStarted = false;
        this.pendingSyncInProgress = false;
        this.syncToast = null;

        this.elements = {
            sessionTimer: document.getElementById("sessionTimer"),
            segmentIndicator: document.getElementById("segmentIndicator"),
            pressureMeterFill: document.getElementById("pressureMeterFill"),
            segmentTransition: document.getElementById("segmentTransition"),
            transitionCountdown: document.getElementById("transitionCountdown"),
            sessionCompleteOverlay: document.getElementById("sessionCompleteOverlay"),
            sessionCompleteProgress: document.getElementById("sessionCompleteProgress"),
            earlyExitLink: document.getElementById("earlyExitLink"),
            earlyExitLogoLink: document.getElementById("earlyExitLogoLink"),
            confirmEarlyExitButton: document.getElementById("confirmEarlyExitButton"),
            earlyExitReason: document.getElementById("earlyExitReason"),
            temporalInjection: document.getElementById("temporalInjection"),
            temporalCountdown: document.getElementById("temporalCountdown"),
            distractorInjection: document.getElementById("distractorInjection"),
            distractorDots: Array.from(document.querySelectorAll("#distractorDotGrid .pp-distractor-dot")),
            interlocutorInjection: document.getElementById("interlocutorInjection"),
            interlocutorAvatar: document.getElementById("interlocutorAvatar"),
            topicPivotInjection: document.getElementById("topicPivotInjection"),
            topicPivotQuestion: document.getElementById("topicPivotQuestion"),
            topicPivotDismiss: document.getElementById("topicPivotDismiss")
        };

        this.earlyExitModal = null;
        const modalElement = document.getElementById("earlyExitModal");
        if (modalElement && window.bootstrap && window.bootstrap.Modal) {
            this.earlyExitModal = new window.bootstrap.Modal(modalElement);
        }

        this.bindDomEvents();
    }

    bindDomEvents() {
        if (this.elements.earlyExitLink) {
            this.elements.earlyExitLink.addEventListener("click", (event) => {
                event.preventDefault();
                this.openEarlyExitModal();
            });
        }

        if (this.elements.earlyExitLogoLink) {
            this.elements.earlyExitLogoLink.addEventListener("click", (event) => {
                event.preventDefault();
                this.openEarlyExitModal();
            });
        }

        if (this.elements.confirmEarlyExitButton) {
            this.elements.confirmEarlyExitButton.addEventListener("click", () => {
                const reason = this.elements.earlyExitReason ? this.elements.earlyExitReason.value : "Other";
                this.handleEarlyExit(reason || "Other");
                if (this.earlyExitModal) {
                    this.earlyExitModal.hide();
                }
            });
        }

        if (this.elements.topicPivotDismiss) {
            this.elements.topicPivotDismiss.addEventListener("click", () => {
                this.logInjectionEvent(
                    "topic_pivot_dismiss",
                    this.getCurrentSessionSeconds(),
                    this.currentPressureValue()
                );
                this.hideTopicPivotInjection();
            });
        }

        window.addEventListener("beforeunload", () => {
            this.destroy();
        });

        document.addEventListener("pp:connectivity", (event) => {
            if (event && event.detail && event.detail.online) {
                this.syncPendingChunks();
            }
        });
    }

    openEarlyExitModal() {
        if (this.earlyExitModal) {
            this.earlyExitModal.show();
        }
    }

    async init() {
        try {
            await this.requestMicrophonePermission();
            await this.startSession();
        } catch (error) {
            this.showFatalError(error && error.message ? error.message : "Unable to start session.");
        }
    }

    requestMicrophonePermission() {
        return new Promise((resolve, reject) => {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                reject(new Error("This browser does not support microphone recording."));
                return;
            }

            navigator.mediaDevices
                .getUserMedia({ audio: true, video: false })
                .then((stream) => {
                    stream.getTracks().forEach((track) => track.stop());
                    resolve(stream);
                })
                .catch((error) => {
                    if (error && error.name === "NotAllowedError") {
                        this.showMicrophonePermissionError();
                    }
                    reject(error);
                });
        });
    }

    async startSession() {
        this.sessionStartTime = Date.now();
        this.segmentStartTime = this.sessionStartTime;

        this.startSessionTimer();

        const stream = await this.startRecorder();
        if (stream) {
            this.stream = stream;
        }

        this.initWaveform(this.stream);

        const injectionDelay = Math.max(0, Number(this.sessionCalibration.timing_seconds || 0) * 1000);
        window.setTimeout(() => {
            this.triggerInjection(
                this.sessionCalibration.injection_type,
                Number(this.sessionCalibration.intensity || 0)
            );
        }, injectionDelay);

        this.startSegmentCountdown();
        this.segmentTransitionTimeout = window.setTimeout(() => {
            this.handleSegmentTransition();
        }, this.segmentDuration * 1000);

        const totalDuration = (this.segmentDuration * this.totalSegments + this.transitionDuration) * 1000;
        this.sessionCompletionTimeout = window.setTimeout(() => {
            this.handleSessionComplete();
        }, totalDuration);
    }

    startSessionTimer() {
        const update = () => {
            if (!this.elements.sessionTimer || !this.sessionStartTime) {
                return;
            }
            const elapsed = Math.max(0, Math.floor((Date.now() - this.sessionStartTime) / 1000));
            const minutes = Math.floor(elapsed / 60);
            const seconds = String(elapsed % 60).padStart(2, "0");
            this.elements.sessionTimer.textContent = `${minutes}:${seconds}`;
        };

        update();
        this.timerInterval = window.setInterval(update, 1000);
    }

    startSegmentCountdown() {
        const update = () => {
            if (!this.elements.segmentIndicator || !this.segmentStartTime) {
                return;
            }
            const elapsed = Math.floor((Date.now() - this.segmentStartTime) / 1000);
            const remaining = Math.max(0, this.segmentDuration - elapsed);
            const mm = Math.floor(remaining / 60);
            const ss = String(remaining % 60).padStart(2, "0");
            this.elements.segmentIndicator.textContent = `Segment ${this.currentSegment} of ${this.totalSegments} - ${mm}:${ss} remaining`;
        };

        update();
        if (this.segmentInterval) {
            window.clearInterval(this.segmentInterval);
        }
        this.segmentInterval = window.setInterval(update, 1000);
    }

    async startRecorder() {
        this.recorder = new window.AudioRecorder({
            chunkInterval: 3000,
            onChunk: (blob) => {
                this.uploadChunk(blob);
            },
            onError: (error) => {
                this.handleRecordingError(error);
            }
        });

        const stream = await this.recorder.start();
        this.stream = stream;
        return stream;
    }

    async uploadChunk(chunkBlob, retryCount = 0) {
        if (!navigator.onLine) {
            await this.queueChunkForSync(chunkBlob);
            return;
        }

        const formData = new FormData();
        formData.append("chunk", chunkBlob, `session_${this.sessionId}_${this.chunkIndex}.webm`);
        formData.append("chunk_index", String(this.chunkIndex));
        formData.append("csrf_token", this.csrfToken);

        try {
            const response = await fetch(this.audioChunkUrl, {
                method: "POST",
                body: formData,
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": this.csrfToken
                }
            });

            if (!response.ok) {
                throw new Error("Chunk upload failed.");
            }

            this.chunkIndex += 1;
        } catch (error) {
            if (retryCount < 1 && navigator.onLine) {
                window.setTimeout(() => {
                    this.uploadChunk(chunkBlob, retryCount + 1);
                }, 2000);
                return;
            }
            await this.queueChunkForSync(chunkBlob);
        }
    }

    blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                const result = reader.result || "";
                const parts = String(result).split(",");
                resolve(parts.length > 1 ? parts[1] : "");
            };
            reader.onerror = () => reject(reader.error || new Error("Unable to read audio chunk."));
            reader.readAsDataURL(blob);
        });
    }

    async queueChunkForSync(chunkBlob) {
        if (!window.PPDB || !chunkBlob) {
            return;
        }

        try {
            const base64 = await this.blobToBase64(chunkBlob);
            const filename = `session_${this.sessionId}_${this.chunkIndex}.webm`;
            await window.PPDB.addPendingSync(
                "audio_chunk",
                this.audioChunkUrl,
                "POST",
                {
                    chunk_base64: base64,
                    mime_type: chunkBlob.type || "audio/webm",
                    filename,
                    chunk_index: this.chunkIndex,
                    csrf_token: this.csrfToken,
                    headers: {
                        "X-CSRFToken": this.csrfToken,
                    },
                },
                {
                    "X-CSRFToken": this.csrfToken,
                }
            );
            this.chunkIndex += 1;
            this.registerBackgroundSync();
        } catch (error) {
            return;
        }
    }

    registerBackgroundSync() {
        if (!("serviceWorker" in navigator)) {
            return;
        }
        navigator.serviceWorker.ready
            .then((registration) => {
                if (registration && "sync" in registration) {
                    return registration.sync.register("pp-background-sync");
                }
                return null;
            })
            .catch(() => null);
    }

    showSyncToast(message) {
        const existing = document.getElementById("ppSessionSyncToast");
        if (existing) {
            return existing;
        }

        const container = document.createElement("div");
        container.className = "toast-container position-fixed bottom-0 end-0 p-3";
        container.style.zIndex = "2000";

        const toastEl = document.createElement("div");
        toastEl.id = "ppSessionSyncToast";
        toastEl.className = "toast text-bg-warning border-0";
        toastEl.setAttribute("role", "status");
        toastEl.setAttribute("aria-live", "polite");
        toastEl.setAttribute("aria-atomic", "true");
        toastEl.innerHTML = `<div class="toast-body fw-semibold">${message}</div>`;

        container.appendChild(toastEl);
        document.body.appendChild(container);

        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = new window.bootstrap.Toast(toastEl, { autohide: false });
            toast.show();
        } else {
            toastEl.classList.add("show");
        }

        return toastEl;
    }

    hideSyncToast() {
        const toastEl = document.getElementById("ppSessionSyncToast");
        if (!toastEl) {
            return;
        }
        if (window.bootstrap && window.bootstrap.Toast) {
            const toast = window.bootstrap.Toast.getInstance(toastEl);
            if (toast) {
                toast.hide();
            } else {
                toastEl.classList.remove("show");
            }
        } else {
            toastEl.classList.remove("show");
        }
        window.setTimeout(() => {
            if (toastEl.parentElement) {
                toastEl.parentElement.remove();
            }
        }, 300);
    }

    async syncPendingChunks() {
        if (!window.PPDB || this.pendingSyncInProgress) {
            return;
        }

        const pending = await window.PPDB.getPendingSync();
        const audioItems = pending.filter((item) => item.type === "audio_chunk");
        if (!audioItems.length) {
            return;
        }

        this.pendingSyncInProgress = true;
        this.showSyncToast("Reconnected. Syncing your session recording...");

        for (const item of audioItems) {
            try {
                const payload = item.body || item.payload || {};
                const headers = payload.headers || item.headers || {};
                const binary = atob(payload.chunk_base64 || "");
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i += 1) {
                    bytes[i] = binary.charCodeAt(i);
                }
                const blob = new Blob([bytes], { type: payload.mime_type || "audio/webm" });
                const formData = new FormData();
                formData.append("chunk", blob, payload.filename || "chunk.webm");
                formData.append("chunk_index", String(payload.chunk_index || 0));
                if (payload.csrf_token) {
                    formData.append("csrf_token", payload.csrf_token);
                }

                const response = await fetch(item.url, {
                    method: "POST",
                    credentials: "same-origin",
                    headers,
                    body: formData,
                });
                if (response.ok) {
                    await window.PPDB.removePendingSync(item.id);
                }
            } catch (error) {
                continue;
            }
        }

        this.pendingSyncInProgress = false;
        this.hideSyncToast();
    }

    triggerInjection(type, intensity) {
        if (!type || type === "none") {
            return;
        }

        this.injectionFired = true;
        const safeIntensity = Math.max(0, Math.min(1, Number(intensity || 0)));

        this.logInjectionEvent(type, this.getCurrentSessionSeconds(), safeIntensity);

        if (this.elements.pressureMeterFill) {
            this.elements.pressureMeterFill.style.height = `${Math.round(safeIntensity * 100)}%`;
        }

        if (type === "temporal") {
            this.showTemporalInjection();
            return;
        }

        if (type === "distractor") {
            this.showDistractorInjection();
            return;
        }

        if (type === "interlocutor") {
            this.showInterlocutorInjection();
            return;
        }

        if (type === "topic_pivot") {
            this.showTopicPivotInjection();
        }
    }

    showTemporalInjection() {
        const overlay = this.elements.temporalInjection;
        const countdown = this.elements.temporalCountdown;
        if (!overlay || !countdown) {
            return;
        }

        overlay.classList.remove("hidden");
        overlay.style.opacity = "1";

        let remaining = 20;
        countdown.textContent = String(remaining);

        const timer = window.setInterval(() => {
            remaining -= 1;
            countdown.textContent = String(Math.max(remaining, 0));

            if (remaining <= 5) {
                countdown.classList.add("pp-countdown-urgent");
            }

            if (remaining <= 0) {
                window.clearInterval(timer);
                overlay.style.opacity = "0";
                window.setTimeout(() => {
                    overlay.classList.add("hidden");
                    overlay.style.opacity = "1";
                    countdown.classList.remove("pp-countdown-urgent");
                }, 500);
            }
        }, 1000);
    }

    showDistractorInjection() {
        const overlay = this.elements.distractorInjection;
        const dots = this.elements.distractorDots;
        if (!overlay || !dots || dots.length < 16) {
            return;
        }

        overlay.classList.remove("hidden");
        overlay.style.opacity = "1";

        const activateDots = () => {
            dots.forEach((dot) => dot.classList.remove("pp-dot-active"));

            const picks = new Set();
            while (picks.size < 6) {
                picks.add(Math.floor(Math.random() * dots.length));
            }

            picks.forEach((index) => {
                dots[index].classList.add("pp-dot-active");
            });
        };

        activateDots();
        this.distractorInterval = window.setInterval(activateDots, 800);

        window.setTimeout(() => {
            if (this.distractorInterval) {
                window.clearInterval(this.distractorInterval);
                this.distractorInterval = null;
            }
            overlay.style.opacity = "0";
            window.setTimeout(() => {
                dots.forEach((dot) => dot.classList.remove("pp-dot-active"));
                overlay.classList.add("hidden");
                overlay.style.opacity = "1";
            }, 350);
        }, 30000);
    }

    showInterlocutorInjection() {
        const overlay = this.elements.interlocutorInjection;
        const avatar = this.elements.interlocutorAvatar;
        if (!overlay || !avatar) {
            return;
        }

        overlay.classList.remove("hidden");
        overlay.style.opacity = "1";
        avatar.src = "/static/img/avatars/avatar_impatient.svg";
        avatar.classList.add("pp-avatar-impatient");

        window.setTimeout(() => {
            avatar.src = "/static/img/avatars/avatar_neutral.svg";
            avatar.classList.remove("pp-avatar-impatient");
            overlay.style.opacity = "0.3";
        }, 15000);
    }

    showTopicPivotInjection() {
        const overlay = this.elements.topicPivotInjection;
        const text = this.elements.topicPivotQuestion;
        if (!overlay || !text) {
            return;
        }

        const bank = Array.isArray(window.pivotQuestions) ? window.pivotQuestions : [];
        if (!bank.length) {
            return;
        }

        const choice = bank[Math.floor(Math.random() * bank.length)];
        text.textContent = choice;

        overlay.classList.remove("hidden");
        window.requestAnimationFrame(() => {
            overlay.classList.add("pp-slide-up");
        });

        if (this.topicPivotTimeout) {
            window.clearTimeout(this.topicPivotTimeout);
        }
        this.topicPivotTimeout = window.setTimeout(() => {
            this.logInjectionEvent(
                "topic_pivot_auto_dismiss",
                this.getCurrentSessionSeconds(),
                this.currentPressureValue()
            );
            this.hideTopicPivotInjection();
        }, 8000);
    }

    hideTopicPivotInjection() {
        const overlay = this.elements.topicPivotInjection;
        if (!overlay) {
            return;
        }

        overlay.classList.remove("pp-slide-up");
        window.setTimeout(() => {
            overlay.classList.add("hidden");
        }, 400);

        if (this.topicPivotTimeout) {
            window.clearTimeout(this.topicPivotTimeout);
            this.topicPivotTimeout = null;
        }
    }

    async logInjectionEvent(type, firedAtSeconds, pressureValue) {
        try {
            await fetch(this.audioChunkUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.csrfToken,
                    Accept: "application/json"
                },
                body: JSON.stringify({
                    injection_event: {
                        injection_type: type,
                        fired_at_seconds: Number(firedAtSeconds.toFixed(2)),
                        pressure_meter_value: Number((pressureValue || 0).toFixed(2))
                    }
                })
            });
        } catch (error) {
            return;
        }
    }

    async handleSegmentTransition() {
        if (this.currentSegment >= this.totalSegments) {
            return;
        }

        if (this.recorder) {
            this.recorder.stop();
        }

        if (this.segmentInterval) {
            window.clearInterval(this.segmentInterval);
            this.segmentInterval = null;
        }

        const overlay = this.elements.segmentTransition;
        const countdownEl = this.elements.transitionCountdown;

        if (!overlay || !countdownEl) {
            this.currentSegment = 2;
            this.segmentStartTime = Date.now();
            const stream = await this.startRecorder();
            if (this.waveform) {
                this.waveform.stop();
            }
            this.initWaveform(stream);
            this.startSegmentCountdown();
            return;
        }

        overlay.classList.remove("hidden");
        let remaining = this.transitionDuration;
        countdownEl.textContent = String(remaining);

        await new Promise((resolve) => {
            const timer = window.setInterval(async () => {
                remaining -= 1;
                countdownEl.textContent = String(Math.max(remaining, 0));

                if (remaining <= 0) {
                    window.clearInterval(timer);
                    overlay.classList.add("hidden");

                    this.currentSegment = 2;
                    this.segmentStartTime = Date.now();
                    const stream = await this.startRecorder();
                    if (this.waveform) {
                        this.waveform.stop();
                    }
                    this.initWaveform(stream);
                    this.startSegmentCountdown();
                    resolve();
                }
            }, 1000);
        });
    }

    async handleSessionComplete() {
        if (this.completionStarted) {
            return;
        }
        this.completionStarted = true;

        if (this.recorder) {
            this.recorder.stop();
            this.recorder = null;
        }

        if (this.waveform) {
            this.waveform.stop();
            this.waveform = null;
        }

        this.clearAllIntervals();

        this.showCompletionOverlay();

        try {
            const response = await fetch(this.sessionCompleteUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.csrfToken,
                    Accept: "application/json"
                },
                body: JSON.stringify({
                    early_exit: this.earlyExitTriggered,
                    early_exit_reason: this.earlyExitReason || null,
                    total_duration_seconds: Number(this.getCurrentSessionSeconds().toFixed(2)),
                    injection_fired: this.injectionFired
                })
            });

            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || "Unable to complete session.");
            }

            const statusUrl = payload.redirect_poll;
            this.completionPollInterval = window.setInterval(async () => {
                try {
                    const statusResponse = await fetch(statusUrl, {
                        method: "GET",
                        credentials: "same-origin",
                        headers: {
                            Accept: "application/json"
                        }
                    });

                    const statusPayload = await statusResponse.json();
                    if (!statusResponse.ok) {
                        return;
                    }

                    if (statusPayload.status === "completed") {
                        window.clearInterval(this.completionPollInterval);
                        window.location.assign(statusPayload.redirect);
                        return;
                    }

                    if (statusPayload.status === "failed") {
                        window.clearInterval(this.completionPollInterval);
                        this.renderCompleteError(
                            `${statusPayload.message || "Session analysis failed."} <a href="/session/new">Start a new session</a>`
                        );
                    }
                } catch (error) {
                    return;
                }
            }, 3000);
        } catch (error) {
            this.renderCompleteError(`${error.message} <a href="/session/new">Start a new session</a>`);
        }
    }

    handleEarlyExit(reason) {
        this.earlyExitTriggered = true;
        this.earlyExitReason = reason;
        this.handleSessionComplete();
    }

    getCurrentSessionSeconds() {
        if (!this.sessionStartTime) {
            return 0;
        }
        return (Date.now() - this.sessionStartTime) / 1000;
    }

    currentPressureValue() {
        if (!this.elements.pressureMeterFill) {
            return 0;
        }
        const raw = this.elements.pressureMeterFill.style.height || "0%";
        const numeric = Number(raw.replace("%", ""));
        if (Number.isNaN(numeric)) {
            return 0;
        }
        return Math.max(0, Math.min(1, numeric / 100));
    }

    initWaveform(stream) {
        if (!stream || !window.WaveformVisualizer) {
            return;
        }

        this.waveform = new window.WaveformVisualizer("waveformContainer", {
            barCount: 7,
            barColor: "#F59E0B",
            barWidth: 6,
            barGap: 4,
            minHeight: 4,
            maxHeight: 40
        });

        try {
            this.waveform.init(stream);
        } catch (error) {
            this.waveform = null;
        }
    }

    showCompletionOverlay() {
        const overlay = this.elements.sessionCompleteOverlay;
        const bar = this.elements.sessionCompleteProgress;
        if (!overlay || !bar) {
            return;
        }

        overlay.classList.remove("hidden");
        let progress = 0;
        bar.style.width = "0%";
        bar.setAttribute("aria-valuenow", "0");

        this.completeOverlayProgressInterval = window.setInterval(() => {
            progress = Math.min(100, progress + 4);
            bar.style.width = `${progress}%`;
            bar.setAttribute("aria-valuenow", String(progress));

            if (progress >= 100) {
                window.clearInterval(this.completeOverlayProgressInterval);
                this.completeOverlayProgressInterval = null;
            }
        }, 200);
    }

    renderCompleteError(messageHtml) {
        const overlay = this.elements.sessionCompleteOverlay;
        if (!overlay) {
            return;
        }

        overlay.innerHTML = `
            <div class="text-center" style="max-width:560px;">
                <h2 class="h4 text-white mb-3">Analysis could not finish.</h2>
                <p class="text-white-50 mb-0">${messageHtml}</p>
            </div>
        `;
    }

    handleRecordingError(error) {
        const message = error && error.message ? error.message : "Recording error occurred.";
        this.showFatalError(message);
    }

    showMicrophonePermissionError() {
        const container = document.querySelector(".session-runtime-shell");
        if (!container) {
            return;
        }

        container.innerHTML = `
            <div class="d-flex align-items-center justify-content-center" style="min-height:100vh; padding:1.5rem;">
                <div class="card" style="max-width:640px; width:100%;">
                    <div class="card-body p-4">
                        <h1 class="h4 mb-3">Microphone permission is required</h1>
                        <p class="text-secondary mb-3">Allow microphone access in your browser settings, then refresh this page to continue.</p>
                        <ul class="mb-3">
                            <li>Chrome: site settings, microphone, allow</li>
                            <li>Edge: site permissions, microphone, allow</li>
                            <li>Firefox: permissions, microphone, allow</li>
                        </ul>
                        <a class="btn btn-primary" href="/session/new">Back to session setup</a>
                    </div>
                </div>
            </div>
        `;
    }

    showFatalError(message) {
        const container = document.querySelector(".session-runtime-shell");
        if (!container) {
            return;
        }

        container.innerHTML = `
            <div class="d-flex align-items-center justify-content-center" style="min-height:100vh; padding:1.5rem;">
                <div class="card" style="max-width:640px; width:100%;">
                    <div class="card-body p-4">
                        <h1 class="h4 mb-3">Session could not continue</h1>
                        <p class="text-secondary mb-3">${message}</p>
                        <a class="btn btn-primary" href="/session/new">Return to session setup</a>
                    </div>
                </div>
            </div>
        `;
    }

    clearAllIntervals() {
        const timers = [
            "timerInterval",
            "segmentInterval",
            "segmentTransitionTimeout",
            "sessionCompletionTimeout",
            "topicPivotTimeout",
            "distractorInterval",
            "completionPollInterval",
            "completeOverlayProgressInterval"
        ];

        timers.forEach((key) => {
            if (!this[key]) {
                return;
            }
            window.clearInterval(this[key]);
            window.clearTimeout(this[key]);
            this[key] = null;
        });
    }

    destroy() {
        this.clearAllIntervals();

        if (this.recorder) {
            try {
                this.recorder.stop();
            } catch (error) {
                this.recorder = null;
            }
            this.recorder = null;
        }

        if (this.waveform) {
            try {
                this.waveform.stop();
            } catch (error) {
                this.waveform = null;
            }
            this.waveform = null;
        }

        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
    }
}

window.SessionController = SessionController;

document.addEventListener("DOMContentLoaded", () => {
    if (typeof sessionCalibration === "undefined") {
        return;
    }

    const controller = new SessionController({
        sessionCalibration,
        audioChunkUrl,
        sessionCompleteUrl,
        csrfToken,
        sessionId,
        segmentDuration,
        transitionDuration
    });

    window.ppSessionController = controller;
    controller.init();
});
