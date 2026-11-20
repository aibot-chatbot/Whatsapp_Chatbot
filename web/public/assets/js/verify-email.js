
        const email = sessionStorage.getItem("pending_verification_email");
        if (!email) {
            window.location.href = "register.html";
        }
        document.getElementById("user-email").innerText = email;

        function showMessage(msg, isError = true) {
            const el = document.getElementById('general-message');
            el.innerHTML = (isError ? '⚠️ ' : '✅ ') + msg;
            el.style.color = isError ? '#F87171' : '#34D399';
            el.style.background = isError ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)';
            el.style.borderColor = isError ? 'rgba(239, 68, 68, 0.3)' : 'rgba(16, 185, 129, 0.3)';
            el.style.display = 'block';
        }

        const inputs = document.querySelectorAll('.otp-inputs input');
        inputs.forEach((input, index) => {
            input.addEventListener('input', (e) => {
                document.getElementById('general-message').style.display = 'none';
                if (e.target.value && index < inputs.length - 1) {
                    inputs[index + 1].focus();
                }
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Backspace' && !e.target.value && index > 0) {
                    inputs[index - 1].focus();
                }
            });
        });

        document.getElementById('otp-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            document.getElementById('general-message').style.display = 'none';
            const otp = Array.from(inputs).map(i => i.value).join('');
            const btn = document.getElementById('verify-btn');
            btn.disabled = true;
            btn.innerText = "Verifying...";

            try {
                const response = await fetch("/api/auth/verify-otp", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email, otp })
                });

                const result = await response.json();
                if (response.ok) {
                    showMessage("Email verified successfully! You can now login.", false);
                    btn.innerText = "Redirecting...";
                    setTimeout(() => {
                        window.location.href = "login.html";
                    }, 1500);
                } else {
                    showMessage(result.message || "Verification failed");
                    btn.disabled = false;
                    btn.innerText = "Verify Account";
                }
            } catch (err) {
                showMessage("Server error");
                btn.disabled = false;
                btn.innerText = "Verify Account";
            }
        });

        let timeLeft = 60;
        function startTimer() {
            const link = document.getElementById('resend-link');
            const timer = document.getElementById('timer');
            link.classList.add('disabled');
            const interval = setInterval(() => {
                timeLeft--;
                timer.innerText = `in ${timeLeft}s`;
                if (timeLeft <= 0) {
                    clearInterval(interval);
                    link.classList.remove('disabled');
                    timer.innerText = "";
                    timeLeft = 60;
                }
            }, 1000);
        }
        startTimer();

        async function resendOTP() {
            try {
                await fetch("/api/auth/resend-otp", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email })
                });
                showMessage("New code sent!", false);
                startTimer();
            } catch (err) {
                showMessage("Failed to resend code");
            }
        }
    