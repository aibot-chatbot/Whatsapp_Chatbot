
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

        const regForm = document.getElementById('register-form');
        const submitBtn = document.getElementById('submit-btn');

        regForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            submitBtn.classList.add('loading');
            document.getElementById('general-error').style.display = 'none';

            const firstName = document.getElementById("first_name").value.trim();
            const lastName = document.getElementById("last_name").value.trim();
            const companyName = document.getElementById("company_name").value.trim();
            const email = document.getElementById("email").value.trim();
            const password = document.getElementById("password").value;
            const confirmPassword = document.getElementById("confirm_password").value;

            const matchError = document.getElementById('password-match-error');
            if (password !== confirmPassword) {
                matchError.style.display = 'block';
                submitBtn.classList.remove('loading');
                return;
            } else {
                matchError.style.display = 'none';
            }

            try {
                const response = await fetch("/api/auth/register", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        first_name: firstName,
                        last_name: lastName,
                        company_name: companyName,
                        email: email,
                        password: password,
                        confirm_password: confirmPassword
                    })
                });

                const result = await response.json();

                if (!response.ok) {
                    const errorMsg = result.message || result.error || "Registration failed.";
                    if (errorMsg.toLowerCase().includes("email") || errorMsg.toLowerCase().includes("user already exists") || errorMsg.toLowerCase().includes("registered")) {
                        const emailError = document.getElementById('email-error');
                        emailError.innerHTML = '⚠️ ' + errorMsg;
                        emailError.style.display = 'block';
                    } else {
                        const generalError = document.getElementById('general-error');
                        generalError.innerHTML = '⚠️ ' + errorMsg;
                        generalError.style.display = 'block';
                    }
                    submitBtn.classList.remove('loading');
                    return;
                }

                // Store email in sessionStorage for the verification page
                sessionStorage.setItem("pending_verification_email", email);
                
                const generalMsg = document.getElementById('general-error');
                generalMsg.innerHTML = '✅ ' + result.message;
                generalMsg.style.color = '#34D399';
                generalMsg.style.background = 'rgba(16, 185, 129, 0.1)';
                generalMsg.style.borderColor = 'rgba(16, 185, 129, 0.3)';
                generalMsg.style.display = 'block';
                
                submitBtn.classList.remove('loading');
                submitBtn.innerHTML = 'Redirecting...';
                
                setTimeout(() => {
                    window.location.href = "verify-email.html";
                }, 1500);

            } catch (error) {
                console.error("Register error:", error);
                alert("Cannot connect to server.");
                submitBtn.classList.remove('loading');
            }
        });

        // ---- Google OAuth Logic ----
        let _pendingGoogleCredential = null;
        let googleLibraryLoaded = false;
        let googleClientId = '';
        let googleInitialized = false;

        function showGoogleAuthError(message) {
            const generalError = document.getElementById('general-error');
            if (generalError) {
                generalError.textContent = message || 'Google Sign-In is currently unavailable.';
                generalError.style.color = '#F87171';
                generalError.style.background = 'rgba(239, 68, 68, 0.1)';
                generalError.style.borderColor = 'rgba(239, 68, 68, 0.3)';
                generalError.style.display = 'block';
            }
        }

        function showGoogleCompanyError(message) {
            const errorEl = document.getElementById('google-company-error');
            if (errorEl) {
                errorEl.textContent = message;
                errorEl.style.display = 'block';
            }
        }

        function clearGoogleCompanyForm() {
            const companyInput = document.getElementById('modal-company-name');
            const passwordInput = document.getElementById('google-company-password');
            const confirmInput = document.getElementById('google-company-confirm-password');
            const errorEl = document.getElementById('google-company-error');
            if (companyInput) companyInput.value = '';
            if (passwordInput) passwordInput.value = '';
            if (confirmInput) confirmInput.value = '';
            if (errorEl) {
                errorEl.textContent = '';
                errorEl.style.display = 'none';
            }
        }

        function onGoogleCredentialResponse(response) {
            if (!response || !response.credential) {
                showGoogleAuthError('Google sign-in could not be completed. Please try again.');
                return;
            }
            sendGoogleCredential(response.credential, null);
        }

        function hideGoogleRegisterButton() {
            const button = document.getElementById('googleRegisterButton');
            if (button) button.innerHTML = '';
        }

        function getGoogleRegisterButtonWidth() {
            const button = document.getElementById('googleRegisterButton');
            const availableWidth = button && button.parentElement ? button.parentElement.clientWidth : 400;
            return Math.min(400, availableWidth || 400);
        }

        function initializeGoogleRegisterOption() {
            if (googleInitialized || !googleLibraryLoaded || !googleClientId) {
                return;
            }
            if (typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
                hideGoogleRegisterButton();
                return;
            }

            try {
                google.accounts.id.initialize({
                    client_id: googleClientId,
                    callback: onGoogleCredentialResponse
                });
                google.accounts.id.renderButton(
                    document.getElementById('googleRegisterButton'),
                    { type: 'standard', shape: 'rectangular', theme: 'filled_black', text: 'continue_with', size: 'large', width: getGoogleRegisterButtonWidth() }
                );
                googleInitialized = true;
            } catch (err) {
                hideGoogleRegisterButton();
                showGoogleAuthError('Google Sign-In is currently unavailable.');
            }
        }

        function handleGoogleLibraryLoad() {
            googleLibraryLoaded = typeof google !== 'undefined' && !!google.accounts && !!google.accounts.id;
            initializeGoogleRegisterOption();
        }

        function handleGoogleLibraryError() {
            googleLibraryLoaded = false;
            hideGoogleRegisterButton();
            showGoogleAuthError('Google Sign-In is currently unavailable.');
        }

        async function loadGoogleConfiguration() {
            try {
                const res = await fetch('/api/auth/google-config');
                const result = await res.json();
                const runtimeClientId = result && result.data && result.data.client_id;
                if (!res.ok || result.status !== 'success' || typeof runtimeClientId !== 'string' || !runtimeClientId.trim()) {
                    hideGoogleRegisterButton();
                    showGoogleAuthError('Google Sign-In is currently unavailable.');
                    return;
                }
                googleClientId = runtimeClientId.trim();
                initializeGoogleRegisterOption();
            } catch (err) {
                hideGoogleRegisterButton();
                showGoogleAuthError('Google Sign-In is currently unavailable.');
            }
        }

        async function sendGoogleCredential(credential, companyName, completion) {
            try {
                const payload = { credential, company_name: companyName || '' };
                if (completion) {
                    payload.password = completion.password || '';
                    payload.confirm_password = completion.confirm_password || '';
                }
                const res = await fetch('/api/auth/google', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const result = await res.json();

                if (result.status === 'needs_company') {
                    _pendingGoogleCredential = credential;
                    document.getElementById('company-modal').classList.add('open');
                    setTimeout(() => document.getElementById('modal-company-name').focus(), 100);
                    return;
                }

                if (result.status === 'success') {
                    if (!establishAuthenticatedSession(result.user, result.token)) {
                        alert('Sign-up could not be completed. Please try again.');
                        return;
                    }
                    window.location.href = 'bots.html';
                } else {
                    if (completion) {
                        showGoogleCompanyError(result.message || 'Google sign-up failed. Please try again.');
                    } else {
                        alert(result.message || 'Google sign-up failed. Please try again.');
                    }
                }
            } catch (err) {
                console.error('Google auth error:', err);
                alert('Cannot connect to server. Please try again.');
            }
        }

        async function submitGoogleWithCompany() {
            const companyName = document.getElementById('modal-company-name').value.trim();
            const password = document.getElementById('google-company-password').value;
            const confirmPassword = document.getElementById('google-company-confirm-password').value;
            const errorEl = document.getElementById('google-company-error');
            if (errorEl) {
                errorEl.textContent = '';
                errorEl.style.display = 'none';
            }
            if (!companyName) { document.getElementById('modal-company-name').focus(); return; }
            if (!password) {
                showGoogleCompanyError('Password is required.');
                document.getElementById('google-company-password').focus();
                return;
            }
            if (!confirmPassword) {
                showGoogleCompanyError('Please confirm your password.');
                document.getElementById('google-company-confirm-password').focus();
                return;
            }
            if (password !== confirmPassword) {
                showGoogleCompanyError('Passwords do not match.');
                document.getElementById('google-company-confirm-password').focus();
                return;
            }

            const btn = document.getElementById('btn-confirm-company');
            btn.querySelector('.btn-confirm-text').style.visibility = 'hidden';
            btn.querySelector('#confirm-loader').style.display = 'block';
            btn.disabled = true;

            await sendGoogleCredential(_pendingGoogleCredential, companyName, {
                password: password,
                confirm_password: confirmPassword
            });

            btn.querySelector('.btn-confirm-text').style.visibility = '';
            btn.querySelector('#confirm-loader').style.display = 'none';
            btn.disabled = false;
        }

        function closeCompanyModal() {
            document.getElementById('company-modal').classList.remove('open');
            _pendingGoogleCredential = null;
            clearGoogleCompanyForm();
        }

        document.addEventListener('DOMContentLoaded', () => {
            document.getElementById('modal-company-name').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') submitGoogleWithCompany();
            });
            document.getElementById('google-company-password').addEventListener('input', () => {
                const errorEl = document.getElementById('google-company-error');
                if (errorEl) errorEl.style.display = 'none';
            });
            document.getElementById('google-company-confirm-password').addEventListener('input', () => {
                const errorEl = document.getElementById('google-company-error');
                if (errorEl) errorEl.style.display = 'none';
            });
        });

        loadGoogleConfiguration();

        // Google renders this button optimistically. If the page origin is not
        // listed in the OAuth client's Authorized JavaScript origins, Google
        // answers 403 a few seconds later and collapses the button iframe to
        // 0x0 rather than telling the page anything - so the user sees an empty
        // gap, or clicks a button that only fails at Google's consent screen.
        // Poll briefly, then fall back to the same message a failed library
        // load already shows. Never throws: a health check must not be able to
        // break sign-in.
        function verifyGoogleButtonRendered(attempt) {
            try {
                attempt = attempt || 0;
                const slot = document.getElementById('googleRegisterButton');
                if (!slot) {
                    return;
                }
                let healthy = false;
                if (googleInitialized) {
                    const frame = slot.querySelector('iframe');
                    const box = (frame || slot).getBoundingClientRect();
                    healthy = box.width > 0 && box.height > 0;
                }
                if (healthy) {
                    return;
                }
                if (attempt < 4) {
                    setTimeout(function () { verifyGoogleButtonRendered(attempt + 1); }, 2500);
                    return;
                }
                if (!googleInitialized) {
                    // Never initialised: a missing client id or a failed library
                    // load, both of which their own handlers already cover.
                    return;
                }
                hideGoogleRegisterButton();
                showGoogleAuthError('Google Sign-In is currently unavailable.');
            } catch (err) {
                /* health check must stay silent */
            }
        }

        setTimeout(function () { verifyGoogleButtonRendered(0); }, 3000);

    