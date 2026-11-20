
        function togglePasswordVisibility(inputId, button) {
            const input = document.getElementById(inputId);
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            button.textContent = isHidden ? 'Hide' : 'Show';
            button.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        }

        function checkPasswordStrength(password) {
            const container = document.getElementById('password-strength-container');
            const bar = document.getElementById('strength-bar');
            const text = document.getElementById('strength-text');
            
            if (!password) {
                container.style.display = 'none';
                return;
            }
            
            container.style.display = 'block';
            let strength = 0;
            let feedback = "";
            
            if (password.length >= 8) strength += 25;
            if (/[A-Z]/.test(password)) strength += 25;
            if (/[0-9]/.test(password)) strength += 25;
            if (/[!@#$%^&*()\-=_+[\]{}|;:,.<>?]/.test(password)) strength += 25;
            
            bar.style.width = strength + "%";
            
            if (strength <= 25) {
                bar.style.background = "#F87171";
                feedback = "Weak (Need 8+ chars, caps, nums, symbols)";
            } else if (strength <= 50) {
                bar.style.background = "#f59e0b";
                feedback = "Moderate";
            } else if (strength <= 75) {
                bar.style.background = "#22D3EE";
                feedback = "Good";
            } else {
                bar.style.background = "#34D399";
                feedback = "Strong Password ✨";
            }
            
            text.innerText = feedback;
        }

        const step1Form = document.getElementById('step-1-form');
        const step2Form = document.getElementById('step-2-form');
        const step1Btn = document.getElementById('step-1-btn');
        const step2Btn = document.getElementById('step-2-btn');
        const alertBox = document.getElementById('alert-box');

        let userEmail = "";
        let resendCooldown = null;

        function startResendCooldown(seconds) {
            const btn = document.getElementById('resend-btn');
            if (!btn) return;
            btn.disabled = true;
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
            let remaining = seconds;
            btn.textContent = `Resend in ${remaining}s`;
            resendCooldown = setInterval(() => {
                remaining--;
                if (remaining <= 0) {
                    clearInterval(resendCooldown);
                    btn.disabled = false;
                    btn.style.opacity = '1';
                    btn.style.cursor = 'pointer';
                    btn.textContent = 'Resend Code';
                } else {
                    btn.textContent = `Resend in ${remaining}s`;
                }
            }, 1000);
        }

        async function resendCode() {
            if (!userEmail) return;
            const btn = document.getElementById('resend-btn');
            btn.disabled = true;
            btn.textContent = 'Sending...';
            try {
                const response = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email: userEmail })
                });
                const result = await response.json();
                if (response.ok) {
                    showAlert('A new verification code has been sent to your email.', 'success');
                    startResendCooldown(60);
                } else {
                    showAlert(result.message || 'Failed to resend code.');
                    btn.disabled = false;
                    btn.textContent = 'Resend Code';
                }
            } catch (error) {
                showAlert('Cannot connect to server. Please try again.');
                btn.disabled = false;
                btn.textContent = 'Resend Code';
            }
        }

        function showAlert(message, type = "error") {
            alertBox.innerText = message;
            alertBox.style.display = "block";
            alertBox.className = `alert alert-${type}`;
        }

        function hideAlert() {
            alertBox.style.display = "none";
        }

        // STEP 1 Form Handler: Request OTP code
        step1Form.addEventListener('submit', async function(e) {
            e.preventDefault();
            hideAlert();

            const email = document.getElementById('reset-email').value.trim();
            if (!email) return;

            step1Btn.classList.add('loading');

            try {
                const response = await fetch("/api/auth/forgot-password", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email: email })
                });

                const result = await response.json();

                if (!response.ok) {
                    showAlert(result.message || result.error || "Failed to send reset code.");
                    step1Btn.classList.remove('loading');
                    return;
                }

                userEmail = email;
                showAlert(result.message, "success");
                step1Btn.classList.remove('loading');

                // Switch step forms
                step1Form.style.display = "none";
                step2Form.style.display = "block";
                startResendCooldown(60);

            } catch (error) {
                console.error("Forgot password error:", error);
                showAlert("Cannot connect to the server.");
                step1Btn.classList.remove('loading');
            }
        });

        // STEP 2 Form Handler: Reset password with OTP
        step2Form.addEventListener('submit', async function(e) {
            e.preventDefault();
            hideAlert();

            const otp = document.getElementById('reset-otp').value.trim();
            const password = document.getElementById('reset-password-input').value;
            const confirmPassword = document.getElementById('reset-password-confirm').value;

            if (password !== confirmPassword) {
                showAlert("Passwords do not match.");
                return;
            }

            step2Btn.classList.add('loading');

            try {
                // First verify OTP
                const verifyRes = await fetch("/api/auth/verify-reset-otp", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ email: userEmail, otp: otp })
                });

                const verifyResult = await verifyRes.json();

                if (!verifyRes.ok) {
                    showAlert(verifyResult.message || verifyResult.error || "Invalid OTP code.");
                    step2Btn.classList.remove('loading');
                    return;
                }

                // If OTP verified, perform actual password reset
                const resetRes = await fetch("/api/auth/reset-password", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        email: userEmail,
                        otp: otp,
                        password: password,
                        confirm_password: confirmPassword
                    })
                });

                const resetResult = await resetRes.json();

                if (!resetRes.ok) {
                    showAlert(resetResult.message || resetResult.error || "Password reset failed.");
                    step2Btn.classList.remove('loading');
                    return;
                }

                showAlert("Password successfully reset! Redirecting to login...", "success");
                step2Btn.classList.remove('loading');

                // Redirect to login page after 3 seconds
                setTimeout(() => {
                    window.location.href = "login.html";
                }, 3000);

            } catch (error) {
                console.error("Password reset error:", error);
                showAlert("An error occurred during password reset.");
                step2Btn.classList.remove('loading');
            }
        });
    