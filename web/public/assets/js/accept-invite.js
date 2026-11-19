
        var inviteIsValid = false;
        var googleLibraryLoaded = false;
        var googleClientId = '';
        var googleInitialized = false;

        // ── Helper: toggle password visibility ──
        function togglePwd(inputId, btn) {
            var input = document.getElementById(inputId);
            var hidden = input.type === 'password';
            input.type = hidden ? 'text' : 'password';
            btn.textContent = hidden ? 'Hide' : 'Show';
            btn.setAttribute('aria-label', hidden ? 'Hide password' : 'Show password');
        }

        // ── Helper: show message in inviteMessage box ──
        function showMessage(type, text) {
            var el = document.getElementById('inviteMessage');
            el.className = 'message-box ' + type;
            el.textContent = text;
            el.style.display = 'block';
        }

        function hideMessage() {
            var el = document.getElementById('inviteMessage');
            el.style.display = 'none';
            el.className = 'message-box';
        }

        // ── Helper: show/hide UI sections ──
        function showLoading() {
            document.getElementById('loadingState').style.display = 'block';
            document.getElementById('invalidState').style.display = 'none';
            document.getElementById('formSection').style.display = 'none';
            document.getElementById('successState').style.display = 'none';
        }

        function showForm(data) {
            inviteIsValid = true;
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('invalidState').style.display = 'none';
            document.getElementById('formSection').style.display = 'block';
            document.getElementById('successState').style.display = 'none';
            // Fill in invite details
            if (data.email) {
                document.getElementById('invitedEmail').textContent = data.email;
            }
            if (data.role) {
                var roleLabel = data.role === 'admin' ? 'Admin' : 'Member';
                document.getElementById('invitedRole').textContent = roleLabel;
            }
            document.getElementById('companyDisplay').textContent = 'your organization';
            initializeGoogleInviteOption();
        }

        function showInvalid(title, message) {
            inviteIsValid = false;
            hideGoogleInviteOption();
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('invalidState').style.display = 'block';
            document.getElementById('formSection').style.display = 'none';
            document.getElementById('successState').style.display = 'none';
            document.getElementById('invalidTitle').textContent = title || 'Invalid Invitation';
            document.getElementById('invalidMessage').textContent = message || 'This invite link is invalid or has expired.';
        }

        function showSuccess() {
            document.getElementById('loadingState').style.display = 'none';
            document.getElementById('invalidState').style.display = 'none';
            document.getElementById('formSection').style.display = 'none';
            document.getElementById('successState').style.display = 'block';
        }

        // ── Password strength validation ──
        function validatePassword(pwd) {
            if (pwd.length < 8) return 'Password must be at least 8 characters.';
            if (!/[A-Z]/.test(pwd)) return 'Password must contain at least 1 uppercase letter.';
            if (!/[0-9]/.test(pwd)) return 'Password must contain at least 1 number.';
            if (!/[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]/.test(pwd)) return 'Password must contain at least 1 special character.';
            return null;
        }

        // ── Form submit ──
        async function handleSubmit(e) {
            e.preventDefault();
            hideMessage();

            var fullName = document.getElementById('fullName').value.trim();
            var password = document.getElementById('password').value;
            var confirmPassword = document.getElementById('confirmPassword').value;

            if (!fullName) {
                showMessage('error', 'Full name is required.');
                return false;
            }
            if (!password) {
                showMessage('error', 'Password is required.');
                return false;
            }
            if (!confirmPassword) {
                showMessage('error', 'Please confirm your password.');
                return false;
            }
            if (password !== confirmPassword) {
                showMessage('error', 'Passwords do not match.');
                return false;
            }

            var pwdErr = validatePassword(password);
            if (pwdErr) {
                showMessage('error', pwdErr);
                return false;
            }

            var token = getTokenFromUrl();
            if (!token) {
                showMessage('error', 'Invalid invite link. Missing token.');
                return false;
            }

            // Show loading on button
            var btn = document.getElementById('submitBtn');
            btn.classList.add('loading');
            btn.disabled = true;

            try {
                var res = await fetch('/api/invites/accept', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        token: token,
                        full_name: fullName,
                        password: password
                    })
                });

                var result = await res.json();

                if (result.status === 'success') {
                    showSuccess();
                    // Redirect to login after 2.5 seconds
                    setTimeout(function() {
                        window.location.href = 'login.html';
                    }, 2500);
                } else {
                    showMessage('error', result.message || 'Failed to create account. Please try again.');
                }
            } catch (err) {
                console.error('Accept invite error:', err);
                showMessage('error', 'Cannot connect to server. Please try again.');
            } finally {
                btn.classList.remove('loading');
                btn.disabled = false;
            }

            return false;
        }

        // ── Extract token from URL ──
        function getTokenFromUrl() {
            var params = new URLSearchParams(window.location.search);
            return params.get('token') || '';
        }

        function hideGoogleInviteOption() {
            document.getElementById('googleInviteSection').hidden = true;
        }

        function initializeGoogleInviteOption() {
            if (googleInitialized || !inviteIsValid || !googleLibraryLoaded || !googleClientId) {
                return;
            }
            if (typeof google === 'undefined' || !google.accounts || !google.accounts.id) {
                hideGoogleInviteOption();
                return;
            }

            try {
                google.accounts.id.initialize({
                    client_id: googleClientId,
                    callback: onGoogleInviteCredential
                });
                google.accounts.id.renderButton(
                    document.getElementById('googleInviteButton'),
                    { theme: 'filled_black', size: 'large', width: 320 }
                );
                googleInitialized = true;
                document.getElementById('googleInviteSection').hidden = false;
            } catch (err) {
                hideGoogleInviteOption();
            }
        }

        function handleGoogleLibraryLoad() {
            googleLibraryLoaded = typeof google !== 'undefined' && !!google.accounts && !!google.accounts.id;
            initializeGoogleInviteOption();
        }

        function handleGoogleLibraryError() {
            googleLibraryLoaded = false;
            hideGoogleInviteOption();
        }

        async function loadGoogleConfiguration() {
            try {
                var res = await fetch('/api/auth/google-config');
                var result = await res.json();
                var runtimeClientId = result && result.data && result.data.client_id;
                if (!res.ok || result.status !== 'success' || typeof runtimeClientId !== 'string' || !runtimeClientId.trim()) {
                    hideGoogleInviteOption();
                    return;
                }
                googleClientId = runtimeClientId.trim();
                initializeGoogleInviteOption();
            } catch (err) {
                hideGoogleInviteOption();
            }
        }

        async function onGoogleInviteCredential(response) {
            if (!response || !response.credential) {
                showMessage('error', 'Google sign-in could not be completed. You can continue with your name and password.');
                return;
            }

            var button = document.getElementById('googleInviteButton');
            button.style.pointerEvents = 'none';
            button.setAttribute('aria-busy', 'true');
            try {
                var res = await fetch('/api/auth/google', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ credential: response.credential, invite_token: getTokenFromUrl() })
                });
                var result = await res.json();
                if (!res.ok || result.status !== 'success') throw new Error('google_acceptance_failed');
                if (!establishAuthenticatedSession(result.user, result.token)) throw new Error('Sign-in could not be completed.');
                window.location.href = 'bots.html';
            } catch (err) {
                showMessage('error', 'Google invitation acceptance failed. You can continue with your name and password.');
                button.style.pointerEvents = '';
                button.removeAttribute('aria-busy');
            }
        }

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
                const slot = document.getElementById('googleInviteButton');
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
                hideGoogleInviteOption();
            } catch (err) {
                /* health check must stay silent */
            }
        }

        setTimeout(function () { verifyGoogleButtonRendered(0); }, 3000);


        // ── On page load: validate invite ──
        (async function() {
            var token = getTokenFromUrl();

            if (!token) {
                showInvalid('Invalid Link', 'No invitation token found in the URL.');
                return;
            }

            showLoading();

            try {
                var res = await fetch('/api/invites/validate?token=' + encodeURIComponent(token));
                var result = await res.json();

                if (result.status === 'success' && result.valid) {
                    showForm(result);
                } else {
                    var msg = result.message || 'This invite link is invalid or has expired.';
                    if (res.status === 410) {
                        showInvalid('Invitation Expired', msg);
                    } else {
                        showInvalid('Invalid Invitation', msg);
                    }
                }
            } catch (err) {
                console.error('Validate invite error:', err);
                showInvalid('Connection Error', 'Cannot connect to server. Please try again later.');
            }
        })();
    