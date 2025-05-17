class ChatApp {
    constructor() {
        this.userId = `user_${Math.random().toString(36).substr(2, 9)}`;
        this.roomId = null;
        this.partnerId = null;
        
        this.initElements();
        this.initWebSocket();
        this.setupEventListeners();
    }

    initElements() {
        this.statusElement = document.getElementById('status');
        this.messagesContainer = document.getElementById('messages');
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
    }

    initWebSocket() {
        this.ws = new WebSocket(`ws://${window.location.host}/ws/${this.userId}`);

        this.ws.onopen = () => {
            this.setStatus('Đang tìm người lạ...', 'info');
        };

        this.ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            this.handleMessage(msg);
        };

        this.ws.onerror = (e) => {
            this.setStatus('Lỗi kết nối', 'error');
            this.disableInput();
        };

        this.ws.onclose = () => {
            this.setStatus('Kết nối đã đóng', 'error');
            this.disableInput();
        };
    }

    handleMessage(msg) {
        switch(msg.type) {
            case 'matched':
                this.handleMatched(msg);
                break;
            case 'chat':
                this.displayMessage(msg.text, 'received');
                break;
        }
    }

    handleMatched(msg) {
        this.roomId = msg.room_id;
        this.partnerId = msg.partner;
        this.setStatus(`Đã kết nối với người lạ (ID: ${this.partnerId})`, 'success');
        this.enableInput();
    }

    displayMessage(text, type) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;
        messageDiv.textContent = text;
        this.messagesContainer.appendChild(messageDiv);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    setStatus(text, type) {
        this.statusElement.textContent = text;
        this.statusElement.className = `status-bar ${type}`;
    }

    enableInput() {
        this.messageInput.disabled = false;
        this.sendBtn.disabled = false;
    }

    disableInput() {
        this.messageInput.disabled = true;
        this.sendBtn.disabled = true;
    }

    setupEventListeners() {
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        
        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
    }

    sendMessage() {
        const text = this.messageInput.value.trim();
        if (!text) return;

        const msg = {
            type: 'chat',
            room_id: this.roomId,
            text: text
        };

        this.ws.send(JSON.stringify(msg));
        this.displayMessage(text, 'sent');
        this.messageInput.value = '';
    }
}

// Khởi động ứng dụng
new ChatApp();