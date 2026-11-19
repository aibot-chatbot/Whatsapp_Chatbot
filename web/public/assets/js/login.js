
        const loginForm = document.getElementById('login-form');
        const loginBtn = document.getElementById('login-btn');

        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const email = loginForm.querySelector('input[type="email"]').value;
            const password = document.getElementById('login-password').value;

            loginBtn.classList.add('loading');

            try {
                const response = await fetch("/api/auth/login", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        email: email,
                        password: password
                    })
                });

                const result = await response.json();

                if (!response.ok) {
                    if (result.status === "unverified") {
                        sessionStorage.setItem("pending_verification_email", result.email || email);
                        document.getElementById("login-error").textContent = result.message;
                        document.getElementById("login-error").style.display = "block";
                        window.location.href = "verify-email.html";
                        return;
                    }
                    var errMsg = document.getElementById("login-error");
                    errMsg.textContent = result.error || result.message || "Login failed";
                    errMsg.style.display = "block";
                    loginBtn.classList.remove('loading');
                    return;
                }

                const destination = getLoginDestination(result);
                if (!destination || !establishAuthenticatedSession(result.user, result.token)) {
                    var sessionError = document.getElementById("login-error");
                    sessionError.textContent = "Login could not be completed. Please try again.";
                    sessionError.style.display = "block";
                    loginBtn.classList.remove('loading');
                    return;
                }

                window.location.href = destination;

            } catch (error) {
                console.error("Login error:", error);
                var errMsg = document.getElementById("login-error");
                errMsg.textContent = "Cannot connect to server. Please try again.";
                errMsg.style.display = "block";
                loginBtn.classList.remove('loading');
            }
        });


        // Clear login error when user types
        document.querySelector('#login-form input[type=email]').addEventListener('input', function() {
            document.getElementById("login-error").style.display = "none";
        });
        document.getElementById("login-password").addEventListener("input", function() {
            document.getElementById("login-error").style.display = "none";
        });

        // ---- Google OAuth Logic ----
        let _pendingGoogleCredential = null;
        let googleLibraryLoaded = false;
        let googleClientId = '';
        let googleInitialized = false;

        function togglePasswordVisibility(inputId, button) {
            const input = document.getElementById(inputId);
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            button.textContent = isHidden ? 'Hide' : 'Show';
            button.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        }

        function showGoogleAuthError(message) {
            const errEl = document.getElementById('login-error');
            if (errEl) {
                errEl.textContent = message || 'Google Sign-In is currently unavailable.';
                errEl.style.display = 'block';
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

        function hideGoogleLoginButton() {
            const button = document.getElementById('googleLoginButton');
            if (button) button.innerHTML = '';
        }

        function getGoogleLoginButtonWidth() {
            const button = document.getElementById('googleLoginButton');
            const availableWidth = button && button.parentElement ? button.parentElement.clientWidth : 400;
            return Math.min(400, availableWidth || 400);
        }

        function initializeGoogleLoginOption() {
            if (googleInitialized || !googleLibraryLoaded || !googleClientId) {
                return;
            }
            if (typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
                hideGoogleLoginButton();
                return;
            }

            try {
                google.accounts.id.initialize({
                    client_id: googleClientId,
                    callback: onGoogleCredentialResponse
                });
                google.accounts.id.renderButton(
                    document.getElementById('googleLoginButton'),
                    { type: 'standard', shape: 'rectangular', theme: 'filled_black', text: 'continue_with', size: 'large', width: getGoogleLoginButtonWidth() }
                );
                googleInitialized = true;
            } catch (err) {
                hideGoogleLoginButton();
                showGoogleAuthError('Google Sign-In is currently unavailable.');
            }
        }

        function handleGoogleLibraryLoad() {
            googleLibraryLoaded = typeof google !== 'undefined' && !!google.accounts && !!google.accounts.id;
            initializeGoogleLoginOption();
        }

        function handleGoogleLibraryError() {
            googleLibraryLoaded = false;
            hideGoogleLoginButton();
            showGoogleAuthError('Google Sign-In is currently unavailable.');
        }

        async function loadGoogleConfiguration() {
            try {
                const res = await fetch('/api/auth/google-config');
                const result = await res.json();
                const runtimeClientId = result && result.data && result.data.client_id;
                if (!res.ok || result.status !== 'success' || typeof runtimeClientId !== 'string' || !runtimeClientId.trim()) {
                    hideGoogleLoginButton();
                    showGoogleAuthError('Google Sign-In is currently unavailable.');
                    return;
                }
                googleClientId = runtimeClientId.trim();
                initializeGoogleLoginOption();
            } catch (err) {
                hideGoogleLoginButton();
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
                    // Keep the original Google credential in memory only while the modal is open.
                    _pendingGoogleCredential = credential;
                    document.getElementById('company-modal').classList.add('open');
                    setTimeout(() => document.getElementById('modal-company-name').focus(), 100);
                    return;
                }

                if (result.status === 'success') {
                    const destination = getLoginDestination(result);
                    if (!destination || !establishAuthenticatedSession(result.user, result.token)) {
                        alert('Sign-in could not be completed. Please try again.');
                        return;
                    }
                    window.location.href = destination;
                } else {
                    if (completion) {
                        showGoogleCompanyError(result.message || 'Google sign-in failed. Please try again.');
                    } else {
                        alert(result.message || 'Google sign-in failed. Please try again.');
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
            if (!companyName) {
                document.getElementById('modal-company-name').focus();
                return;
            }
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

        // Allow Enter key in company modal
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

        // Check for deactivation message from previous session
        (function() {
            var msg = sessionStorage.getItem("deactivated_message");
            if (msg) {
                sessionStorage.removeItem("deactivated_message");
                var errEl = document.getElementById("login-error");
                if (errEl) {
                    errEl.textContent = msg;
                    errEl.style.display = "block";
                }
            }
        })();

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
                const slot = document.getElementById('googleLoginButton');
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
                hideGoogleLoginButton();
                showGoogleAuthError('Google Sign-In is currently unavailable.');
            } catch (err) {
                /* health check must stay silent */
            }
        }

        setTimeout(function () { verifyGoogleButtonRendered(0); }, 3000);

    