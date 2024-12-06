const tabButtons = document.querySelectorAll('.tab-button');
const tabContents = document.querySelectorAll('.tab-content');
let currentMode = 'text';

tabButtons.forEach(button => {
    button.addEventListener('click', () => {
        tabButtons.forEach(btn => btn.classList.remove('active'));
        tabContents.forEach(content => {
            content.classList.remove('active');
        });

        button.classList.add('active');
        const mode = button.getAttribute('data-mode');
        currentMode = mode;
        const activeContent = document.getElementById(`${mode}-mode`);
        activeContent.classList.add('active');
    });
});


const summarySlider = document.getElementById('summary-slider');
const sliderLabel = document.getElementById('slider-label');

function updateSliderLabel(value) {
    let label = '';
    if (value === '1') {
        label = 'Key Points';
    } else if (value === '2') {
        label = 'Brief Summary';
    } else if (value === '3') {
        label = 'Detailed Summary';
    }
    sliderLabel.textContent = label;
}

summarySlider.addEventListener('input', () => {
    updateSliderLabel(summarySlider.value);
});


updateSliderLabel(summarySlider.value);


const conversationSlider = document.getElementById('conversation-slider');
const conversationSliderLabel = document.getElementById('conversation-slider-label');

function updateConversationSliderLabel(value) {
    let label = '';
    if (value === '1') {
        label = 'Bullet Points';
    } else if (value === '2') {
        label = 'Concise Explanation';
    } else if (value === '3') {
        label = 'Detailed Explanation';
    }
    conversationSliderLabel.textContent = label;

    sessionStorage.setItem('conversation_type', label);
}

conversationSlider.addEventListener('input', () => {
    updateConversationSliderLabel(conversationSlider.value);
});


updateConversationSliderLabel(conversationSlider.value);


const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    fileInput.files = e.dataTransfer.files;
});


document.getElementById('input-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const summaryValue = summarySlider.value;
    let summaryType;
    if (summaryValue === '1') {
        summaryType = 'key_points';
    } else if (summaryValue === '2') {
        summaryType = 'brief';
    } else if (summaryValue === '3') {
        summaryType = 'detailed';
    }

    const modelChoice = document.getElementById('model-select').value;
    const loadingSpinner = document.getElementById('loading-spinner');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const chatSection = document.getElementById('chat-section');
    const chatWindow = document.getElementById('chat-window');

    const formData = new FormData();
    formData.append('mode', currentMode);
    formData.append('summary_type', summaryType);
    formData.append('model', modelChoice);

    if (currentMode === 'text') {
        const text = document.getElementById('text-input').value.trim();
        if (!text) {
            alert('Please provide text for summarization.');
            return;
        }
        formData.append('text', text);
    } else if (currentMode === 'file') {
        const fileInputElement = document.getElementById('file-input').files[0];
        if (!fileInputElement) {
            alert('Please upload a file.');
            return;
        }
        formData.append('file', fileInputElement);
    } else if (currentMode === 'url') {
        const url = document.getElementById('url-input').value.trim();
        if (!url) {
            alert('Please provide a URL.');
            return;
        }
        formData.append('url', url);
    }

    loadingSpinner.style.display = 'block';
    progressContainer.style.display = 'none';

    try {
        const response = await fetch('/summarize', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        loadingSpinner.style.display = 'none';

        if (data.error) {
            chatSection.classList.add('active');
            chatWindow.innerHTML += `
                <div class="chat-message bot">
                    <div class="message-content">Error: ${data.error}</div>
                </div>
            `;
            chatSection.scrollIntoView({ behavior: 'smooth' });
        } else {
            chatSection.classList.add('active');
            sessionStorage.setItem('conversation_id', data.conversation_id);


            chatWindow.innerHTML = `
                <div class="chat-message bot">
                    <div class="message-content">${data.summary}</div>
                </div>
                <div class="chat-message bot">
                    <div class="message-content">Is there anything I can help you with regarding the material?</div>
                </div>
            `;


            chatSection.scrollIntoView({ behavior: 'smooth' });
        }
    } catch (error) {
        loadingSpinner.style.display = 'none';
        chatSection.classList.add('active');
        chatWindow.innerHTML += `
            <div class="chat-message bot">
                <div class="message-content">An error occurred while processing your request.</div>
            </div>
        `;
        chatSection.scrollIntoView({ behavior: 'smooth' });
    }
});


document.getElementById('send-btn').addEventListener('click', async () => {
    const messageInput = document.getElementById('chat-input');
    const message = messageInput.value.trim();
    const chatWindow = document.getElementById('chat-window');
    const conversationId = sessionStorage.getItem('conversation_id');

    if (!message) {
        alert('Please enter a message.');
        return;
    }


    chatWindow.innerHTML += `
        <div class="chat-message user">
            <div class="message-content">${message}</div>
        </div>
    `;

    messageInput.value = '';
    chatWindow.scrollTop = chatWindow.scrollHeight;

    const conversationType = sessionStorage.getItem('conversation_type') || 'Concise Explanation';

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                conversation_id: conversationId,
                conversation_type: conversationType
            })
        });

        const data = await response.json();

        if (data.error) {
            chatWindow.innerHTML += `
                <div class="chat-message bot">
                    <div class="message-content">Error: ${data.error}</div>
                </div>
            `;
        } else {
            chatWindow.innerHTML += `
                <div class="chat-message bot">
                    <div class="message-content">${data.response}</div>
                </div>
            `;
        }

        chatWindow.scrollTop = chatWindow.scrollHeight;
    } catch (error) {
        chatWindow.innerHTML += `
            <div class="chat-message bot">
                <div class="message-content">An error occurred while processing your request.</div>
            </div>
        `;
    }
});


window.addEventListener('resize', adjustLayout);

function adjustLayout() {
    const bottomControls = document.querySelector('.bottom-controls');
    if (window.innerWidth < 600) {
        bottomControls.style.flexDirection = 'column';
        bottomControls.style.alignItems = 'flex-start';
    } else {
        bottomControls.style.flexDirection = 'row';
        bottomControls.style.alignItems = 'center';
    }
}


adjustLayout();
