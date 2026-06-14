(() => {
    const STEP_MESSAGES = [
        "Transcribing your speech...",
        "Measuring vocabulary patterns...",
        "Analyzing pause behavior...",
        "Building your profile...",
    ];

    function wait(ms) {
        return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    document.addEventListener("DOMContentLoaded", () => {
        const appRoot = document.getElementById("baselineAssessmentApp");
        if (!appRoot) {
            return;
        }

        const config = {
            preparedPrompt: appRoot.dataset.preparedPrompt || "",
            spontaneousPrompt: appRoot.dataset.spontaneousPrompt || "",
            submitUrl: appRoot.dataset.submitUrl || "/api/assessment/baseline",
            statusBaseUrl: (appRoot.dataset.statusBaseUrl || "/api/assessment/status").replace(/\/$/, ""),
            step3Redirect: appRoot.dataset.step3Redirect || "/onboarding/step-3",
        };

        const csrfMeta = document.querySelector("meta[name='csrf-token']");
        const csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";

        const permissionCard = document.getElementById("permissionCard");
        const permissionButton = document.getElementById("allowMicButton");
        const permissionMessage = document.getElementById("permissionMessage");

        const recordingCard = document.getElementById("recordingCard");
        const stageTitle = document.getElementById("stageTitle");
        const stagePrompt = document.getElementById("stagePrompt");
        const countdownValue = document.getElementById("countdownValue");
        const recordingIndicator = document.getElementById("recordingIndicator");

        const countdownOverlay = document.getElementById("countdownOverlay");
        const countdownOverlayValue = document.getElementById("countdownOverlayValue");
        const transitionOverlay = document.getElementById("transitionOverlay");

        const processingOverlay = document.getElementById("processingOverlay");
        const processingText = document.getElementById("processingStepText");
        const processingBar = document.getElementById("processingProgressBar");

        const errorCard = document.getElementById("recordingErrorCard");
        const errorMessage = document.getElementById("recordingErrorMessage");
        const retryButton = document.getElementById("retryAssessmentButton");

        const stages = [
            {
                key: "prepared",
                title: "Stage 1 of 2 - Prepared Speech",
                duration: 120,
                prompt: config.preparedPrompt,
            },
            {
                key: "spontaneous",
                title: "Stage 2 of 2 - Spontaneous Speech",
                duration: 90,
                prompt: config.spontaneousPrompt,
            },
        ];

        let preparedBlob = null;
        let spontaneousBlob = null;
        let recorder = null;
        let visualizer = null;
        let processingMessageTimer = null;
        let statusPollingTimer = null;

        function showError(message) {
            errorMessage.textContent = message;
            errorCard.classList.remove("d-none");
            processingOverlay.classList.add("d-none");
            recordingIndicator.classList.add("d-none");
        }

        function hideError() {
            errorCard.classList.add("d-none");
            errorMessage.textContent = "";
        }

        function updateCountdown(seconds) {
            countdownValue.textContent = String(Math.max(0, seconds));
        }

        function setStage(stage) {
            stageTitle.textContent = stage.title;
            stagePrompt.textContent = stage.prompt;
            updateCountdown(stage.duration);
        }

        async function runGetReadyCountdown() {
            countdownOverlay.classList.remove("d-none");
            for (let counter = 3; counter >= 1; counter -= 1) {
                countdownOverlayValue.textContent = String(counter);
                await wait(1000);
            }
            countdownOverlay.classList.add("d-none");
        }

        async function showTransitionOverlay() {
            transitionOverlay.classList.remove("d-none");
            await wait(2000);
            transitionOverlay.classList.add("d-none");
        }

        function stopRecorderIfRunning() {
            if (recorder) {
                try {
                    recorder.stop();
                } catch (error) {
                    console.error(error);
                }
                recorder = null;
            }
            if (visualizer) {
                visualizer.stop();
                visualizer = null;
            }
        }

        function createRecorder(stage) {
            return new Promise((resolve, reject) => {
                let timerId = null;
                let remaining = stage.duration;

                recorder = new window.AudioRecorder({
                    chunkInterval: 3000,
                    onStop: (blob) => {
                        if (timerId) {
                            window.clearInterval(timerId);
                        }
                        recordingIndicator.classList.add("d-none");
                        if (visualizer) {
                            visualizer.stop();
                        }
                        resolve(blob);
                    },
                    onError: (error) => {
                        if (timerId) {
                            window.clearInterval(timerId);
                        }
                        recordingIndicator.classList.add("d-none");
                        reject(error);
                    },
                    onPermissionDenied: () => {
                        if (timerId) {
                            window.clearInterval(timerId);
                        }
                        recordingIndicator.classList.add("d-none");
                        reject(new Error("Microphone access was denied. Please allow microphone access and try again."));
                    },
                });

                recorder.start().then((stream) => {
                    visualizer = new window.WaveformVisualizer("waveformContainer", {
                        barCount: 7,
                        barColor: "#F59E0B",
                        barWidth: 12,
                        barGap: 10,
                        minHeight: 6,
                        maxHeight: 58,
                    });
                    visualizer.init(stream);

                    recordingIndicator.classList.remove("d-none");
                    updateCountdown(remaining);

                    timerId = window.setInterval(() => {
                        remaining -= 1;
                        updateCountdown(remaining);
                        if (remaining <= 0) {
                            window.clearInterval(timerId);
                            timerId = null;
                            recorder.stop();
                        }
                    }, 1000);
                }).catch((error) => {
                    reject(error);
                });
            });
        }

        async function recordStage(stage) {
            setStage(stage);
            await runGetReadyCountdown();
            return createRecorder(stage);
        }

        async function requestMicrophonePermission() {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error("Your browser does not support microphone recording.");
            }

            const stream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: false,
            });
            stream.getTracks().forEach((track) => track.stop());
        }

        function showProcessingState() {
            processingOverlay.classList.remove("d-none");
            processingBar.style.width = "8%";
            processingBar.setAttribute("aria-valuenow", "8");
            processingText.textContent = STEP_MESSAGES[0];

            let stepIndex = 0;
            processingMessageTimer = window.setInterval(() => {
                stepIndex = (stepIndex + 1) % STEP_MESSAGES.length;
                processingText.textContent = STEP_MESSAGES[stepIndex];
            }, 2500);
        }

        function stopProcessingTimers() {
            if (processingMessageTimer) {
                window.clearInterval(processingMessageTimer);
                processingMessageTimer = null;
            }
            if (statusPollingTimer) {
                window.clearTimeout(statusPollingTimer);
                statusPollingTimer = null;
            }
        }

        function scheduleStatusCheck(checkStatus, delay) {
            if (statusPollingTimer) {
                window.clearTimeout(statusPollingTimer);
            }

            statusPollingTimer = window.setTimeout(() => {
                checkStatus().catch((error) => {
                    stopProcessingTimers();
                    showError(error.message);
                });
            }, delay);
        }

        async function readResponsePayload(response) {
            const contentType = response.headers.get("content-type") || "";
            const rawBody = await response.text();

            if (!rawBody) {
                return null;
            }

            if (contentType.includes("application/json")) {
                try {
                    return JSON.parse(rawBody);
                } catch (error) {
                    console.error("Failed to parse JSON response.", error);
                    return null;
                }
            }

            try {
                return JSON.parse(rawBody);
            } catch (error) {
                return { raw: rawBody };
            }
        }

        async function pollStatus(taskId) {
            const checkStatus = async () => {
                const response = await fetch(`${config.statusBaseUrl}/${encodeURIComponent(taskId)}`, {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                    },
                });

                const payload = await readResponsePayload(response);

                if (response.status === 429) {
                    scheduleStatusCheck(checkStatus, 5000);
                    return;
                }

                if (!response.ok) {
                    throw new Error((payload && (payload.message || payload.error)) || "Failed to fetch assessment status.");
                }

                if (!payload || typeof payload !== "object" || payload.raw) {
                    scheduleStatusCheck(checkStatus, 5000);
                    return;
                }

                if (payload.status === "processing") {
                    const progress = Math.max(8, Math.min(98, Number(payload.progress || 8)));
                    processingBar.style.width = `${progress}%`;
                    processingBar.setAttribute("aria-valuenow", String(progress));
                    scheduleStatusCheck(checkStatus, 3000);
                    return;
                }

                stopProcessingTimers();

                if (payload.status === "completed") {
                    window.location.assign(payload.redirect || config.step3Redirect);
                    return;
                }

                if (payload.status === "failed") {
                    throw new Error(payload.message || "Speech analysis failed. Please try again.");
                }

                throw new Error("Unexpected status response from server.");
            };

            await checkStatus();
        }

        async function uploadBaseline() {
            showProcessingState();

            const formData = new FormData();
            formData.append("audio_prepared", preparedBlob, "prepared.webm");
            formData.append("audio_spontaneous", spontaneousBlob, "spontaneous.webm");
            formData.append("csrf_token", csrfToken);

            const response = await fetch(config.submitUrl, {
                method: "POST",
                body: formData,
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": csrfToken,
                },
            });

            const payload = await readResponsePayload(response);
            if (!response.ok) {
                throw new Error((payload && (payload.error || payload.message)) || "Failed to submit baseline audio.");
            }

            if (payload.status !== "processing" || !payload.task_id) {
                throw new Error("Server did not return a valid task identifier.");
            }

            await pollStatus(payload.task_id);
        }

        async function beginAssessmentFlow() {
            hideError();
            permissionMessage.textContent = "Microphone access granted. Starting baseline recording...";
            permissionButton.disabled = true;

            permissionCard.classList.add("d-none");
            recordingCard.classList.remove("d-none");

            try {
                preparedBlob = await recordStage(stages[0]);
                await showTransitionOverlay();
                spontaneousBlob = await recordStage(stages[1]);
                await uploadBaseline();
            } catch (error) {
                stopRecorderIfRunning();
                stopProcessingTimers();
                showError(error.message || "Unable to complete baseline recording.");
            }
        }

        permissionButton.addEventListener("click", async () => {
            hideError();
            permissionButton.disabled = true;
            permissionMessage.textContent = "Requesting microphone permission...";

            try {
                await requestMicrophonePermission();
                await beginAssessmentFlow();
            } catch (error) {
                permissionButton.disabled = false;
                permissionMessage.textContent = "Microphone access is required to continue.";
                showError(error.message || "Could not access microphone.");
            }
        });

        retryButton.addEventListener("click", () => {
            window.location.reload();
        });
    });
})();
