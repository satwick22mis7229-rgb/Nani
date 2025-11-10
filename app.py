from flask import Flask, render_template_string, request, redirect, url_for, session, g
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from twilio.rest import Client
import os
import base64
from dotenv import load_dotenv

# Load environment variables from .env file (for local testing with DATABASE_URL)
load_dotenv()

# --- CONFIGURATION ---
app = Flask(__name__)

# Use DATABASE_URL from environment if available (Cloud deployment), otherwise fallback to SQLite (local)
cloud_db_url = os.environ.get('DATABASE_URL')
if cloud_db_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = cloud_db_url
else:
    # Fallback to local SQLite ONLY if DATABASE_URL is not set (Development Only)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
    
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Must set a secret key to use Flask sessions
app.secret_key = os.urandom(24)

db = SQLAlchemy(app)
# Flask-Migrate is included but primarily used for flask db upgrade command
migrate = Migrate(app, db)

# WARNING: These credentials MUST be live and correct for OTP to send.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")

# Initialize Twilio Client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# --- COUNTRY CODES CONFIGURATION ---
COUNTRY_CODES = {
    "India (+91)": "+91", 
    "United States (+1)": "+1", 
    "Canada (+1)": "+1", 
    "United Kingdom (+44)": "+44", 
    "Australia (+61)": "+61", 
    "Germany (+49)": "+49", 
    "France (+33)": "+33", 
}

def generate_country_options(default_code="+91"):
    """Generates the HTML options for the country code select element."""
    options_html = ""
    for label, code in COUNTRY_CODES.items():
        selected = 'selected' if code == default_code else ''
        options_html += f'<option value="{code}" {selected}>{label}</option>'
    return options_html
# ----------------------------------------

# Database model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    face_data = db.Column(db.Text, nullable=True) 

# --- CRITICAL: MANUAL TABLE CREATION FOR CLOUD CONNECTION ---
if cloud_db_url:
    with app.app_context():
        try:
            db.create_all()
            print("INFO: Database connection to Cloud DB successful. Tables verified/created.")
        except Exception as e:
            print(f"ERROR: Failed to connect or create tables on Cloud DB. Details: {e}")
else:
    with app.app_context():
        db.create_all()


# Utility function to render consistent error/success messages
def render_status_page(message, is_error=True):
    color = 'red' if is_error else 'green'
    icon = '❌' if is_error else '✅'
    
    # Check if the message indicates successful registration and offer a login button
    login_link = '<a href="/login-factor-choice">Proceed to Login</a>'
    
    return render_template_string(f"""
    <div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
        <h2 style="color: {color}; text-align: center;">{icon} {message}</h2>
        <p style="text-align: center; margin-top: 15px;">{login_link if not is_error else ''} | <a href="/">Home</a></p>
    </div>
    """)

# --- MOCK FACE RECOGNITION FUNCTION ---
def mock_verify_face(reference_data, captured_data):
    """
    Mocks the process of comparing a captured face against a stored reference face.
    Returns True if both reference and captured data exist (simulating success).
    """
    # Simple check for existence and data size to mock a successful capture
    if reference_data and captured_data and len(captured_data) > 100:
        return True
    return False

# --- JAVASCRIPT AND STYLES (UI_SCRIPTS) ---
# NOTE: Updated startCamera and capturePhoto to handle dynamic IDs
UI_SCRIPTS = """
<script>
    const RESEND_COOLDOWN_SECONDS = 120; // 2 minutes

    function togglePasswordVisibility(fieldId, iconId) {
        const passwordField = document.getElementById(fieldId);
        const toggleIcon = document.getElementById(iconId);
        
        if (passwordField.type === 'password') {
            passwordField.type = 'text';
            toggleIcon.textContent = '🔒'; // Locked icon when text is visible
        } else {
            passwordField.type = 'password';
            toggleIcon.textContent = '👁️'; // Eye icon when text is hidden
        }
    }

    function startCountdown(buttonId, timerKey, username, redirectRoute) {
        const resendButton = document.getElementById(buttonId);
        if (!resendButton) return;

        const storageKey = timerKey + '_' + username;
        let storedTime = localStorage.getItem(storageKey);
        let now = Date.now();
        let remainingSeconds = 0;

        if (storedTime) {
            let elapsed = now - parseInt(storedTime, 10);
            remainingSeconds = Math.floor((RESEND_COOLDOWN_SECONDS * 1000 - elapsed) / 1000);
        }

        if (remainingSeconds > 0) {
            resendButton.disabled = true;
            resendButton.textContent = `Resend in (${remainingSeconds}s)`;
            
            let countdownInterval = setInterval(() => {
                remainingSeconds--;
                if (remainingSeconds <= 0) {
                    clearInterval(countdownInterval);
                    resendButton.textContent = 'Resend OTP';
                    resendButton.disabled = false;
                    localStorage.removeItem(storageKey);
                } else {
                    resendButton.textContent = `Resend in (${remainingSeconds}s)`;
                }
            }, 1000);
        } else {
             resendButton.textContent = 'Resend OTP';
             resendButton.disabled = false;
        }

        resendButton.onclick = () => {
            if (!resendButton.disabled) {
                localStorage.setItem(storageKey, Date.now().toString());
                window.location.href = `/resend-otp?username=${username}&next_route=${redirectRoute}`;
            }
        };
    }

    // --- UPDATED COUNTRY CODE HANDLER ---
    function setupCountryCode(selectId, visibleInputId, hiddenInputId) {
        const selectElement = document.getElementById(selectId);
        const visibleInputElement = document.getElementById(visibleInputId);
        const hiddenInputElement = document.getElementById(hiddenInputId);
        const form = visibleInputElement.closest('form');

        function cleanNumber(value) {
            return value.replace(/[^0-9]/g, '').trim();
        }

        function updateHiddenValue() {
            const currentCode = selectElement.value;
            const nationalNumber = cleanNumber(visibleInputElement.value);

            hiddenInputElement.value = currentCode + nationalNumber;
            visibleInputElement.value = nationalNumber; 
        }

        selectElement.onchange = updateHiddenValue;
        visibleInputElement.oninput = updateHiddenValue; 
        visibleInputElement.onblur = updateHiddenValue;
        
        form.onsubmit = function() {
            updateHiddenValue();
            if (!hiddenInputElement.value.startsWith('+') || hiddenInputElement.value.length < 5) {
                return true; 
            }
            return true;
        }
        
        updateHiddenValue();
    }
    
    // --- FACE SCAN JAVASCRIPT (Unified Logic) ---
    let stream;
    let isCapturing = false;

    async function startCamera(videoElementId) {
        const video = document.getElementById(videoElementId);
        const message = document.getElementById('cameraMessage');
        // Handle both button IDs (for setup and login)
        const captureButton = document.getElementById('captureButton') || document.getElementById('captureLoginButton');
        
        if (!video) return;

        try {
            message.textContent = 'Requesting camera access...';
            stream = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } });
            video.srcObject = stream;
            await video.play();
            message.textContent = 'Camera ready. Please center your face.';
            if (captureButton) {
                captureButton.disabled = false;
            }
        } catch (err) {
            message.style.color = 'red';
            message.textContent = 'Error: Could not access camera. Please ensure permissions are granted.';
            console.error("Camera access error:", err);
            if (captureButton) {
                captureButton.disabled = true;
            }
        }
    }

    function capturePhoto(videoElementId, canvasElementId, formInputName, formId) {
        if (isCapturing) return;
        isCapturing = true;

        const video = document.getElementById(videoElementId);
        const canvas = document.getElementById(canvasElementId);
        const context = canvas.getContext('2d');
        const message = document.getElementById('cameraMessage');
        const captureButton = document.getElementById('captureButton') || document.getElementById('captureLoginButton');

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const dataURL = canvas.toDataURL('image/png');
        const faceDataInput = document.getElementById(formInputName);
        faceDataInput.value = dataURL;

        stopCamera();

        message.style.color = 'green';
        message.textContent = 'Photo captured successfully! Submitting for verification...';
        if (captureButton) {
            captureButton.textContent = 'Captured!';
            captureButton.disabled = true;
        }


        setTimeout(() => {
            document.getElementById(formId).submit();
        }, 1000);
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
    }
</script>
<style>
    .password-container {
        position: relative;
    }
    .password-toggle {
        position: absolute;
        right: 10px;
        top: 50%;
        transform: translateY(-50%);
        cursor: pointer;
        font-size: 1.2em;
    }
    .face-scan-container {
        text-align: center;
        background: #f0f4f8;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.1);
    }
    video, canvas {
        display: block;
        margin: 10px auto;
        border: 2px solid #007bff;
        border-radius: 8px;
        background-color: #333;
    }
    button {
        transition: background-color 0.3s;
    }
    /* New styles for phone input group */
    .phone-input-group {
        display: flex;
        gap: 5px;
        align-items: center;
    }
    .phone-input-group select {
        padding: 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
        flex: 0 0 40%; /* Code takes 40% width */
    }
    .phone-input-group input[type="text"] {
        padding: 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
        flex: 1; /* Number takes remaining width */
    }
    .login-buttons {
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin-top: 15px;
    }
</style>
"""

# 1. DASHBOARD HTML TEMPLATE 
dashboard_html = """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 30px; border: 1px solid #1e7e34; border-radius: 8px; background-color: #f8f9fa; box-shadow: 0 4px 12px rgba(0,123,255,0.2);">
    <h1 style="text-align: center; color: #28a745;">✅ Welcome, {{ username }}!</h1>
    <h3 style="text-align: center; color: #333;">Secure Dashboard (Logged in)</h3>
    <hr style="border: 1px solid #ccc;">
    <p style="font-size: 1.1em; color: #555; text-align: center;">You have successfully logged in via {{ login_method }}.</p>
    <div style="margin-top: 20px; padding: 15px; background-color: #e2f0fb; border-radius: 6px;">
        <p><strong>Your Details:</strong></p>
        <ul>
            <li><strong>Email:</strong> {{ email }}</li>
            <li><strong>Phone:</strong> {{ phone }}</li>
        </ul>
    </div>
    <div style="text-align: center; margin-top: 30px;">
        <a href="/logout" style="padding: 10px 20px; font-size: 16px; background-color: #dc3545; color: white; border: none; border-radius: 5px; cursor: pointer; text-decoration: none;">Logout</a>
    </div>
</div>
"""

# 2. FACE SCAN HTML TEMPLATE (Used for Setup and Login)
face_scan_html = """
<div class="face-scan-container" style="font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto;">
    <h2 style="color: #007bff; margin-bottom: 5px;">{{ page_title }}</h2>
    <p id="cameraMessage" style="color: #6c757d; margin-bottom: 15px;">{{ status_message }}</p>

    <video id="webcamVideo" width="320" height="240" autoplay playsinline></video>

    <canvas id="photoCanvas" width="320" height="240" style="display: none;"></canvas>

    <form method="POST" action="{{ action_url }}" id="faceScanForm" style="margin-top: 20px;">
        <input type="hidden" name="username" value="{{ username }}">
        <input type="hidden" id="faceDataInput" name="face_data">
        
        <button type="button" 
            id="captureButton" 
            onclick="capturePhoto('webcamVideo', 'photoCanvas', 'faceDataInput', 'faceScanForm')"
            disabled
            style="padding: 10px 20px; font-size: 16px; background-color: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; width: 100%;">
            {{ button_text }}
        </button>
    </form>
    <p style="margin-top: 15px; color: #dc3545;">NOTE: This is a Mock Face Verification check.</p>
    <div style="margin-top: 20px; text-align: center;">
        <a href="{{ url_for('login_factor_choice') }}" style="color: #007bff; text-decoration: none;">&larr; Back to Login Factor Choice</a>
    </div>
</div>
<script>
    // Start the camera when the page loads
    window.onload = function() {
        startCamera('webcamVideo');
    };
    // Ensure camera stops when navigating away
    window.onbeforeunload = stopCamera;
</script>
"""

# 3. NEW FACTOR CHOICE HTML TEMPLATE
factor_choice_html = """
<div style="font-family: Arial, sans-serif; max-width: 450px; margin: 50px auto; padding: 25px; border: 1px solid #007bff; border-radius: 12px; box-shadow: 0 4px 15px rgba(0, 123, 255, 0.2);">
    <h2 style="text-align: center; color: #007bff; margin-bottom: 20px;">Choose Your Login Factor</h2>
    <p style="color: #666; text-align: center; margin-bottom: 20px;">Select one method to authenticate:</p>
    
    <div class="login-buttons">
        <a href="{{ url_for('login_password_page') }}" style="text-decoration: none;">
            <button style="width: 100%; padding: 12px; font-size: 16px; background-color: #ff5722; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">
                🔑 Login with Password
            </button>
        </a>
        <a href="{{ url_for('login_otp_page') }}" style="text-decoration: none;">
            <button style="width: 100%; padding: 12px; font-size: 16px; background-color: #ffc107; color: #333; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">
                📱 Login with OTP (SMS)
            </button>
        </a>
        <a href="{{ url_for('login_face_page') }}" style="text-decoration: none;">
            <button style="width: 100%; padding: 12px; font-size: 16px; background-color: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;">
                👤 Login with Face Scan
            </button>
        </a>

        <p style="text-align: center; margin-top: 20px;">
            <a href="/logout" style="color: #dc3545; text-decoration: none;">Back to Home</a>
        </p>
    </div>
</div>
"""

# 4. NEW HTML TEMPLATE: Password Login (Corrected URLs)
password_login_html = f"""
{UI_SCRIPTS}
<div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="text-align: center; color: #ff5722;">Login with Password</h2>
    <form method="POST" action="{{{{ action_url }}}}" style="display: grid; gap: 10px;">
        <label>Username:</label>
        <input type="text" name="username" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>Password:</label>
        <div class="password-container">
            <input type="password" id="loginPassword" name="password" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px; width: 100%; box-sizing: border-box;">
            <span class="password-toggle" id="loginToggle" onclick="togglePasswordVisibility('loginPassword', 'loginToggle')">👁️</span>
        </div>
        
        <input type="submit" value="Login" style="padding: 10px; background-color: #ff5722; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
    </form>
    <p style="text-align: center; margin-top: 15px;"><a href="{{{{ url_for('login_factor_choice') }}}}">&larr; Back to Factor Choice</a></p>
</div>
"""

# 5. NEW HTML TEMPLATE: OTP Login (Corrected URLs)
otp_login_html = f"""
{UI_SCRIPTS}
<div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="text-align: center; color: #ffc107;">Login with OTP</h2>
    <p style="color: #666; text-align: center;">Enter your username and registered phone to send the OTP.</p>
    
    <form method="POST" action="{{{{ action_url }}}}" style="display: grid; gap: 10px;">
        <label>Username:</label>
        <input type="text" name="username" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>Phone:</label>
        <div class="phone-input-group">
            <select id="loginOtpCountryCode">
                {generate_country_options(default_code="+91")}
            </select>
            <input type="text" id="loginOtpPhoneVisibleInput" required placeholder="Enter number (without code)">
            <input type="hidden" name="phone" id="loginOtpPhoneHiddenInput">
        </div>
        
        <input type="submit" value="Send OTP" style="padding: 10px; background-color: #ffc107; color: #333; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
    </form>
    <p style="text-align: center; margin-top: 15px;"><a href="{{{{ url_for('login_factor_choice') }}}}">&larr; Back to Factor Choice</a></p>
</div>
<script>
    window.onload = function() {{
        setupCountryCode('loginOtpCountryCode', 'loginOtpPhoneVisibleInput', 'loginOtpPhoneHiddenInput');
    }};
</script>
"""

# 6. NEW HTML TEMPLATE: Face Scan Login (Corrected URLs and IDs)
face_login_html = f"""
{UI_SCRIPTS}
<div class="face-scan-container" style="font-family: Arial, sans-serif; max-width: 500px; margin: 50px auto;">
    <h2 style="color: #28a745; margin-bottom: 5px;">Login with Face Scan</h2>
    <p id="cameraMessage" style="color: #6c757d; margin-bottom: 15px;">Enter your username and click 'Start Camera' to verify your face.</p>

    <form method="POST" action="{{{{ action_url }}}}" id="faceScanLoginForm" style="margin-top: 20px;">
        <label style="display: block; text-align: left; margin-bottom: 5px;">Username:</label>
        <input type="text" name="username" id="faceLoginUsername" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px; width: 100%; box-sizing: border-box; margin-bottom: 10px;">
        
        <button type="button" 
            id="startCameraButton" 
            onclick="startCamera('webcamLoginVideo'); this.style.display='none'; document.getElementById('webcamLoginVideo').style.display='block'; document.getElementById('captureLoginButton').style.display='block'; document.getElementById('cameraMessage').textContent='Camera ready. Please center your face.'" 
            style="padding: 10px 20px; font-size: 16px; background-color: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; width: 100%;">
            Start Camera
        </button>

        <video id="webcamLoginVideo" width="320" height="240" autoplay playsinline style="display: none;"></video>
        <canvas id="photoCanvas" width="320" height="240" style="display: none;"></canvas>
        <input type="hidden" id="faceDataInput" name="face_data">
        
        <button type="button" 
            id="captureLoginButton" 
            onclick="capturePhoto('webcamLoginVideo', 'photoCanvas', 'faceDataInput', 'faceScanLoginForm')"
            disabled
            style="display: none; padding: 10px 20px; font-size: 16px; background-color: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; width: 100%; margin-top: 10px;">
            Capture & Verify Face
        </button>
    </form>
    <p style="margin-top: 15px; color: #dc3545;">NOTE: Face Verification check.</p>
    <div style="margin-top: 20px; text-align: center;">
        <a href="{{{{ url_for('login_factor_choice') }}}}">&larr; Back to Factor Choice</a>
    </div>
</div>
<script>
    // Ensure camera stops when navigating away
    window.onbeforeunload = stopCamera;
</script>
"""

# --- ROUTES ---

@app.route("/")
def home():
    home_html = """
    <div style="font-family: Arial, sans-serif; text-align: center; max-width: 600px; margin: 100px auto;">
        <h1 style="color: #007bff;">Multi-Factor Authentication Portal</h1>
        <p style="color: #555;">--------------------------------------------</p>
        <div style="margin-top: 30px;">
            <a href="/register"><button style="padding:12px 25px; font-size:18px; background-color: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; margin-right: 15px;">Register</button></a>
            <a href="/login"><button style="padding:12px 25px; font-size:18px; background-color: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer;">Login</button></a>
        </div>
        <p style="margin-top: 20px;"><a href="/dashboard">Go to Dashboard (if logged in)</a></p>
    </div>
    """
    return home_html

# --- REGISTRATION FLOW ---

@app.route("/register", methods=["GET", "POST"])
def register():
    register_html = f"""
{UI_SCRIPTS}
<div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="text-align: center; color: #333;">Register</h2>
    <p style="color: #dc3545; text-align: center;">Note: Face ID setup happens next.</p>
    <form method="POST" id="registerForm" style="display: grid; gap: 10px;">
        <label>Username:</label>
        <input type="text" name="username" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>Password:</label>
        <div class="password-container">
            <input type="password" id="registerPassword" name="password" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px; width: 100%; box-sizing: border-box;">
            <span class="password-toggle" id="registerToggle" onclick="togglePasswordVisibility('registerPassword', 'registerToggle')">👁️</span>
        </div>
        
        <label>Email:</label>
        <input type="email" name="email" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>Phone:</label>
        <div class="phone-input-group">
            <select id="registerCountryCode">
                {generate_country_options(default_code="+91")}
            </select>
            <input type="text" id="registerPhoneVisibleInput" required placeholder="Enter number (without code)">
            <input type="hidden" name="phone" id="registerPhoneHiddenInput">
        </div>
        
        <input type="submit" value="Next: Setup Face ID" style="padding: 10px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
    </form>
    <p style="text-align: center; margin-top: 15px;"><a href="/">Home</a></p>
</div>
<script>
    window.onload = function() {{
        setupCountryCode('registerCountryCode', 'registerPhoneVisibleInput', 'registerPhoneHiddenInput');
    }};
</script>
"""
    
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        email = request.form["email"].strip()
        phone = request.form["phone"].strip() 

        # 1. Validation
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_status_page(f'Username "{username}" already exists!')

        if not phone.startswith('+') or len(phone) < 5 or not phone[1:].isdigit():
            return render_status_page('Phone number must be a valid E.164 format (e.g., +911234567890).')

        # 2. Store data in session for final commit after Face Scan (Step 2/2)
        session['registration_data'] = {
            'username': username,
            'password': password,
            'email': email,
            'phone': phone,
        }
        
        # 3. Redirect to Face Scan Setup
        return redirect(url_for('face_scan_page', 
                                username=username, 
                                status_message="Registration Step 2/2: Please set up your Face ID.", 
                                setup=1))

    return render_template_string(register_html)


@app.route("/save-reference-face", methods=["POST"])
def save_reference_face():
    """Saves the captured face image AND finalizes the registration by committing the user to the database."""
    username = request.form["username"].strip()
    face_data = request.form["face_data"]
    
    registration_data = session.get('registration_data')
    
    if not face_data or len(face_data) < 100:
        return redirect(url_for('face_scan_page', 
                                username=username, 
                                status_message="Failed capture. Please ensure the camera is active and try again.", 
                                setup=1))

    # HANDLE REGISTRATION FINALIZATION (User is ONLY in session)
    if registration_data and registration_data['username'] == username:
        try:
            new_user = User(
                username=registration_data['username'],
                password=registration_data['password'],
                email=registration_data['email'],
                phone=registration_data['phone'],
                face_data=face_data # Save the captured face data
            )
            db.session.add(new_user)
            db.session.commit()
            
            # Clear temporary registration data
            session.pop('registration_data', None)
            
            # NEW REDIRECT for successful registration
            return render_status_page(
                f"✅ Registration successfully completed for **{username}**. You can now log in.", 
                is_error=False,
            )
        except Exception as e:
            db.session.rollback()
            return render_status_page(f"CRITICAL ERROR: Failed to save user to database: {e}")
            
    # Fallback for general face data update 
    user = User.query.filter_by(username=username).first()
    if user:
        try:
            user.face_data = face_data
            db.session.commit()
            return render_status_page(f"✅ Face data updated for {username}.", is_error=False)
        except Exception as e:
            return render_status_page(f"Error updating face data: {e}")
            
    # Default fallback
    return redirect(url_for('login'))


# --- LOGIN FACTOR CHOICE (New Primary Login Entry Point) ---

@app.route("/login")
def login():
    """Redirects to the factor choice page."""
    return redirect(url_for('login_factor_choice'))

@app.route("/login-factor-choice")
def login_factor_choice():
    """Renders the page to choose one login factor (Password, OTP, Face)."""
    return render_template_string(UI_SCRIPTS + factor_choice_html)

# ------------------------------------------------------------------
# --- DEDICATED LOGIN HANDLERS (New Single-Factor Logic) ---
# ------------------------------------------------------------------

# 1. PASSWORD LOGIN
@app.route("/login-password", methods=["GET"])
def login_password_page():
    # Fix: Generate the URL within the request context and pass it to the template
    action_url = url_for('login_password_verify')
    return render_template_string(password_login_html, action_url=action_url)

@app.route("/login-password-verify", methods=["POST"])
def login_password_verify():
    username = request.form["username"].strip()
    password = request.form["password"]

    user = User.query.filter_by(username=username, password=password).first()
    
    if user:
        session['logged_in'] = True
        session['username'] = user.username
        session['login_method'] = 'Password'
        return redirect(url_for('dashboard'))
    else:
        return render_status_page('Invalid username or password.')

# 2. OTP LOGIN (Step 1: Send)
@app.route("/login-otp", methods=["GET"])
def login_otp_page():
    # Fix: Generate the URL within the request context and pass it to the template
    action_url = url_for('login_otp_send')
    return render_template_string(otp_login_html, action_url=action_url)

@app.route("/login-otp-send", methods=["POST"])
def login_otp_send():
    username = request.form["username"].strip()
    phone = request.form["phone"].strip() 

    user = User.query.filter_by(username=username, phone=phone).first()

    if not user:
        return render_status_page('User not found or phone number does not match registered account.')

    try:
        # Twilio Verify: Send OTP
        verification = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verifications.create(to=user.phone, channel='sms')
        
        if verification.status == 'pending':
            # Store user info in session for next step
            session['otp_login_pending'] = username
            return redirect(url_for('login_otp_verify_page', 
                                    username=username, 
                                    status_message=f"OTP sent to {user.phone}. Please check your phone."))
        else:
            return render_status_page(f"SMS Delivery Failed. Twilio status: {verification.status}")

    except Exception as e:
        return render_status_page(f"SMS Delivery Failed: Error connecting to Twilio. Status: {e.__class__.__name__}")

# 2. OTP LOGIN (Step 2: Verify)
@app.route("/login-otp-verify", methods=["GET", "POST"])
def login_otp_verify_page():
    status_message = request.args.get('status_message', 'Please check your phone for the OTP.')
    username = request.args.get('username', session.get('otp_login_pending', ''))

    if not username:
        return redirect(url_for('login_otp_page'))

    # If GET, render the verification form
    if request.method == "GET":
        verification_html = f"""
        {UI_SCRIPTS}
        <div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
            <h2 style="text-align: center; color: #ffc107;">Verify OTP (OTP Login)</h2>
            <p style="color: #007bff; text-align: center;">{status_message}</p>
            <form method="POST" action="{url_for('login_otp_verify_page')}" style="display: grid; gap: 10px;">
                <p style="text-align: center; font-weight: bold; margin-bottom: 5px;">Verifying User: {username}</p>
                <input type="hidden" name="username" value="{username}">
                
                <label>OTP:</label>
                <input type="text" name="otp" required maxlength="6" style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
                
                <input type="submit" value="Verify OTP & Login" style="padding: 10px; background-color: #ffc107; color: #333; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
            </form>
            <button id="resendLoginOtpButton" style="padding: 10px; background-color: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 10px; width: 100%;">Resend OTP</button>
            <p style="text-align: center; margin-top: 15px;"><a href="{url_for('login_factor_choice')}">Cancel Login</a></p>
        </div>
        <script>
            window.onload = function() {{
                startCountdown('resendLoginOtpButton', 'login_otp_resend_time', '{username}', 'login_otp_verify_page');
            }};
        </script>
        """
        return render_template_string(verification_html)

    # If POST, verify the OTP
    if request.method == "POST":
        username = request.form["username"].strip()
        otp_code = request.form["otp"]

        user = User.query.filter_by(username=username).first()

        if not user or session.get('otp_login_pending') != username:
            return render_status_page("Session error. Please restart OTP login.")

        try:
            verification_check = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verification_checks.create(to=user.phone, code=otp_code)

            if verification_check.status == 'approved':
                # OTP approved! Login successful.
                session['logged_in'] = True
                session['username'] = username
                session['login_method'] = 'OTP'
                session.pop('otp_login_pending', None)
                return redirect(url_for('dashboard'))
            else:
                return redirect(url_for('login_otp_verify_page', username=username, status_message=f'Invalid OTP for user "{username}".'))

        except Exception as e:
            return render_status_page(f'Verification Failed: Error connecting to Twilio. Status: {e.__class__.__name__}')

# 3. FACE SCAN LOGIN
@app.route("/login-face", methods=["GET"])
def login_face_page():
    # Fix: Generate the URL within the request context and pass it to the template
    action_url = url_for('login_face_verify')
    return render_template_string(UI_SCRIPTS + face_login_html, action_url=action_url)


@app.route("/login-face-verify", methods=["POST"])
def login_face_verify():
    username = request.form["username"].strip()
    captured_face_data = request.form["face_data"]

    user = User.query.filter_by(username=username).first()

    if not user:
        return render_status_page("User not found.")

    if not user.face_data:
        return render_status_page("Face ID not set up for this user. Please use another factor.")

    # Mock Face Verification Check
    is_face_verified = mock_verify_face(user.face_data, captured_face_data)

    if is_face_verified:
        # SUCCESS! Login successful.
        session['logged_in'] = True
        session['username'] = user.username
        session['login_method'] = 'Face Scan'
        return redirect(url_for('dashboard'))
    else:
        # FAILED FACE SCAN
        return render_status_page("Face scan failed! Please try capturing a clearer image.", is_error=True)

# ------------------------------------------------------------------
# --- STANDARD ROUTES (Modified) ---
# ------------------------------------------------------------------

@app.route("/dashboard")
def dashboard():
    """Renders the secure dashboard page if the user is logged in."""
    if 'logged_in' in session and session['logged_in']:
        username = session['username']
        login_method = session.get('login_method', 'Unknown Method')
        user = User.query.filter_by(username=username).first()
        
        if not user:
            session.pop('logged_in', None)
            session.pop('username', None)
            return render_status_page("Authentication error. Please log in again.", is_error=True)

        return render_template_string(
            dashboard_html,
            username=user.username,
            email=user.email,
            phone=user.phone,
            login_method=login_method
        )
    else:
        return redirect(url_for('login'))

@app.route("/logout")
def logout():
    """Logs the user out by clearing the session."""
    # Clear all session variables related to authentication and flow
    keys_to_clear = ['logged_in', 'username', 'login_method', 'otp_login_pending', 'registration_data', 'mfa_pending', 'mfa_flow']
    for key in keys_to_clear:
        session.pop(key, None)
    
    return render_status_page("You have been successfully logged out.", is_error=False)

# --- RESEND OTP (Modified to handle a simpler flow) ---

@app.route("/resend-otp")
def resend_otp():
    username = request.args.get("username").strip()
    next_route = request.args.get("next_route") 

    user = User.query.filter_by(username=username).first()

    if not user:
        if next_route == 'reset_password_page':
            return redirect(url_for('forgot_password'))
        return redirect(url_for('login_otp_page')) # Redirect to initial OTP login page

    try:
        verification = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID) \
            .verifications \
            .create(to=user.phone, channel='sms')
        
        if verification.status == 'pending':
            message = f"New OTP successfully sent to {user.phone}. Please wait 2 minutes before attempting to resend again."
            # Redirect back to the OTP verification page
            return redirect(url_for(next_route, username=username, status_message=message))
        else:
            sms_status = f"OTP initiation failed. Twilio status: {verification.status}"
            return render_status_page(f"SMS Delivery Failed: {sms_status}")

    except Exception as e:
        return render_status_page(f"SMS Delivery Failed: Error connecting to Twilio. Status: {e.__class__.__name__}. Please verify credentials.")

# --- FORGOT PASSWORD ROUTES ---

@app.route("/face-scan-page", methods=["GET"])
def face_scan_page():
    # This route is now primarily used for REGISTRATION SETUP
    username = request.args.get('username')
    status_message = request.args.get('status_message', 'Ready to verify your identity.')
    is_setup = request.args.get('setup') == '1' 

    registration_data = session.get('registration_data')
    
    if not registration_data or registration_data['username'] != username or not is_setup:
        return render_status_page("Please complete Step 1 of registration first.", is_error=True)

    # REGISTRATION FLOW
    title = "Setup Face ID (Step 2/2)"
    button_text = "Capture & Save Reference Face (Finalize Registration)"
    action_url = url_for('save_reference_face')
    message = request.args.get('status_message', "Take a clear photo for your face reference profile.")
            
    return render_template_string(
        UI_SCRIPTS + face_scan_html,
        page_title=title,
        status_message=message,
        username=username,
        action_url=action_url,
        button_text=button_text
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    forgot_password_html = f"""
{UI_SCRIPTS}
<div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="text-align: center; color: #ffc107;">Forgot Password</h2>
    <p style="color: #666; text-align: center;">Enter your username and registered phone to receive a verification code.</p>
    <form method="POST" id="forgotPasswordForm" style="display: grid; gap: 10px;">
        <label>Username:</label>
        <input type="text" name="username" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>Registered Phone:</label>
        <div class="phone-input-group">
            <select id="forgotCountryCode">
                {generate_country_options(default_code="+91")}
            </select>
            <input type="text" id="forgotPhoneVisibleInput" required placeholder="Enter number (without code)">
            <input type="hidden" name="phone" id="forgotPhoneHiddenInput">
        </div>
        
        <input type="submit" value="Send Reset OTP" style="padding: 10px; background-color: #ffc107; color: #333; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
    </form>
    <p style="text-align: center; margin-top: 15px;"><a href="{{{{ url_for('login_factor_choice') }}}}">Back to Login Choice</a> | <a href="/">Home</a></p>
</div>
<script>
    window.onload = function() {{
        setupCountryCode('forgotCountryCode', 'forgotPhoneVisibleInput', 'forgotPhoneHiddenInput');
    }};
</script>
"""
    
    if request.method == "POST":
        username = request.form["username"].strip()
        phone = request.form["phone"].strip() 

        if not phone.startswith('+') or len(phone) < 5 or not phone[1:].isdigit():
            return render_status_page('Phone number must be a valid E.164 format.')

        user = User.query.filter_by(username=username, phone=phone).first()

        if not user:
            return render_status_page('User not found or phone number does not match registered account.')

        try:
            verification = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID) \
                .verifications \
                .create(to=user.phone, channel='sms')
            
            if verification.status == 'pending':
                return redirect(url_for('reset_password_page', username=user.username, status_message=f"OTP sent to {user.phone}. Please check your phone."))
            else:
                sms_status = f"OTP initiation failed. Twilio status: {verification.status}"
                return render_status_page(f"SMS Delivery Failed: {sms_status}")
        
        except Exception as e:
            return render_status_page(f"SMS Delivery Failed: Error connecting to Twilio. Status: {e.__class__.__name__}. Please verify credentials.")

    return render_template_string(forgot_password_html)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password_page():
    reset_password_html = UI_SCRIPTS + """
<div style="font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; border: 1px solid #ccc; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="text-align: center; color: #ffc107;">Reset Password</h2>
    <p style="color: #666; text-align: center;">Enter the code sent to your phone and choose a new password.</p>
    <form method="POST" style="display: grid; gap: 10px;">
        <p style="text-align: center; font-weight: bold; margin-bottom: 5px;">User: {{ username or '' }}</p>
        <input type="hidden" name="username" value="{{ username or '' }}">
        
        <label>Verification Code (OTP):</label>
        <input type="text" name="otp" required maxlength="6" style="padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
        
        <label>New Password:</label>
        <div class="password-container">
            <input type="password" id="resetPassword" name="new_password" required style="padding: 10px; border: 1px solid #ddd; border-radius: 4px; width: 100%; box-sizing: border-box;">
            <span class="password-toggle" id="resetToggle" onclick="togglePasswordVisibility('resetPassword', 'resetToggle')">👁️</span>
        </div>

        <input type="submit" value="Reset Password" style="padding: 10px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 15px;">
    </form>
    <button id="resendResetOtpButton" style="padding: 10px; background-color: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; margin-top: 10px; width: 100%;">Resend OTP</button>
    <p style="text-align: center; margin-top: 15px;"><a href="{{{{ url_for('login_factor_choice') }}}}">Back to Login Choice</a> | <a href="/">Home</a></p>
</div>
<script>
    window.onload = function() {
        startCountdown('resendResetOtpButton', 'reset_resend_time', '{{ username or \'\' }}', 'reset_password_page');
    };
</script>
"""
    if request.method == "GET":
        # Render the form, pre-filling the username from the query arg
        username_from_arg = request.args.get('username', '')
        status_message = request.args.get('status_message', '')
        
        if not username_from_arg:
            return redirect(url_for('forgot_password'))

        template = reset_password_html.replace('{{ username or \'\' }}', username_from_arg)
        return render_template_string(template)

    if request.method == "POST":
        username = request.form["username"].strip()
        otp_code = request.form["otp"]
        new_password = request.form["new_password"]
        
        user = User.query.filter_by(username=username).first()

        if not user:
            return render_status_page(f'User "{username}" not found.')
        
        # Twilio Verify: Check the OTP code
        try:
            verification_check = twilio_client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID) \
                .verification_checks \
                .create(to=user.phone, code=otp_code)

            if verification_check.status == 'approved':
                # OTP approved, now reset the password
                user.password = new_password
                db.session.commit()
                return render_status_page(f'Password reset successful for user "{username}". You can now log in.', is_error=False)
            else:
                return redirect(url_for('reset_password_page', username=username, status_message='Invalid OTP. Please try again.'))

        except Exception as e:
            return render_status_page(f'Verification Failed: Error connecting to Twilio. Status: {e.__class__.__name__}')


if __name__ == "__main__":
    app.run(debug=True)