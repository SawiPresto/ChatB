const catCompanion = document.getElementById('cat-companion');
let catResetTimer = null;
let scrollAnimationFrame = null;

function smoothScrollToBottom(container, duration = 420) {
    if (!container) return;

    if (scrollAnimationFrame) {
        cancelAnimationFrame(scrollAnimationFrame);
    }

    const start = container.scrollTop;
    const target = container.scrollHeight - container.clientHeight;
    const distance = target - start;

    if (Math.abs(distance) < 2) {
        container.scrollTop = target;
        return;
    }

    const startTime = performance.now();
    const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

    const step = (now) => {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        container.scrollTop = start + (distance * easeOutCubic(progress));

        if (progress < 1) {
            scrollAnimationFrame = requestAnimationFrame(step);
        } else {
            scrollAnimationFrame = null;
        }
    };

    scrollAnimationFrame = requestAnimationFrame(step);
}

function setCatState(state) {
    if (!catCompanion) return;
    catCompanion.classList.remove('cat-state-idle', 'cat-state-thinking', 'cat-state-happy');
    catCompanion.classList.add(`cat-state-${state}`);
}

function triggerHappyThenIdle() {
    if (catResetTimer) {
        clearTimeout(catResetTimer);
    }
    setCatState('happy');
    catResetTimer = setTimeout(() => {
        setCatState('idle');
    }, 1800);
}

async function sendMessage() {
    const userInput = document.getElementById('user-input').value.trim();
    if (!userInput) return;  // Handle empty input

    const chatMessages = document.getElementById('chat-messages');
    const sendButton = document.getElementById('send-button');
    const userInputEl = document.getElementById('user-input');

    // Disable send button and change text
    sendButton.disabled = true;
    sendButton.textContent = "Memproses...";
    setCatState('thinking');

    // Add user message to chat
    const userMessageContainer = document.createElement('div');
    userMessageContainer.classList.add('message-container', 'user-message-container');
    const userMessage = document.createElement('div');
    userMessage.textContent = userInput;
    userMessage.classList.add('user-message');
    userMessageContainer.appendChild(userMessage);
    chatMessages.appendChild(userMessageContainer);

    // Clear input after sending message
    document.getElementById('user-input').value = '';

    // Add typing indicator
    const typingIndicator = document.createElement('div');
    typingIndicator.classList.add('message-container', 'system-message-container');
    const typingIndicatorText = document.createElement('div');
    typingIndicatorText.classList.add('system-message');
    typingIndicatorText.innerHTML = '<div class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
    typingIndicator.appendChild(typingIndicatorText);
    chatMessages.appendChild(typingIndicator);

    // Scroll chat container to the bottom with smooth behavior
    smoothScrollToBottom(chatMessages);

    // Add loading animation to button
    sendButton.classList.add('loading');

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                messages: [
                    { role: 'user', content: userInput }
                ],
                model: 'openai/gpt-oss-120b'
            })
        });

        const data = await response.json().catch(() => ({}));

        // Remove typing indicator
        if (chatMessages.contains(typingIndicator)) {
            chatMessages.removeChild(typingIndicator);
        }

        if (!response.ok) {
            throw new Error(data.error || 'Terjadi kesalahan saat menghubungi server.');
        }

        // Add system message with typing effect
        const systemMessageContainer = document.createElement('div');
        systemMessageContainer.classList.add('message-container', 'system-message-container');
        const systemMessage = document.createElement('div');
        systemMessage.classList.add('system-message');
        systemMessageContainer.appendChild(systemMessage);
        chatMessages.appendChild(systemMessageContainer);

        const text = data.response || 'Tidak ada respons dari model.';
        const paragraphs = text.split('\n\n'); // Split response into paragraphs

        // Simulate typing effect
        await typeMessage(systemMessage, paragraphs);

        // Enable send button and change text back
        sendButton.disabled = false;
        sendButton.textContent = "Kirim";
        sendButton.classList.remove('loading');
        userInputEl.focus();
        triggerHappyThenIdle();
    } catch (error) {
        console.error('Error:', error);
        // Ensure to remove the typing indicator if an error occurs
        if (chatMessages.contains(typingIndicator)) {
            chatMessages.removeChild(typingIndicator);
        }

        const errorContainer = document.createElement('div');
        errorContainer.classList.add('message-container', 'system-message-container');
        const errorMessage = document.createElement('div');
        errorMessage.classList.add('system-message');
        errorMessage.textContent = `Error: ${error.message || 'Permintaan gagal diproses.'}`;
        errorContainer.appendChild(errorMessage);
        chatMessages.appendChild(errorContainer);

        // Enable send button and change text back
        sendButton.disabled = false;
        sendButton.textContent = "Kirim";
        sendButton.classList.remove('loading');
        userInputEl.focus();
        setCatState('idle');
    } finally {
        // Ensure scroll is at the bottom after messages are added
        smoothScrollToBottom(chatMessages);
    }
}

function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatInline(text) {
    let output = escapeHtml(text);

    output = output.replace(/`([^`]+)`/g, '<code>$1</code>');
    output = output.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    output = output.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    output = output.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    output = output.replace(/_([^_\n]+)_/g, '<em>$1</em>');
    output = output.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    return output;
}

function renderMarkdownBlocks(text) {
    const lines = text.replace(/\r\n/g, '\n').split('\n');
    const blocks = [];
    let i = 0;

    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();

        if (!trimmed) {
            i += 1;
            continue;
        }

        if (trimmed.startsWith('```')) {
            const codeLines = [];
            i += 1;
            while (i < lines.length && !lines[i].trim().startsWith('```')) {
                codeLines.push(lines[i]);
                i += 1;
            }
            if (i < lines.length) {
                i += 1;
            }

            const pre = document.createElement('pre');
            const code = document.createElement('code');
            code.textContent = codeLines.join('\n');
            pre.appendChild(code);
            blocks.push(pre);
            continue;
        }

        if (/^#{1,6}\s+/.test(trimmed)) {
            const level = Math.min(6, trimmed.match(/^#{1,6}/)[0].length);
            const heading = document.createElement(`h${level}`);
            heading.innerHTML = formatInline(trimmed.replace(/^#{1,6}\s+/, ''));
            blocks.push(heading);
            i += 1;
            continue;
        }

        if (/^>\s?/.test(trimmed)) {
            const quoteLines = [];
            while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
                quoteLines.push(lines[i].trim().replace(/^>\s?/, ''));
                i += 1;
            }
            const blockquote = document.createElement('blockquote');
            blockquote.innerHTML = formatInline(quoteLines.join('<br>'));
            blocks.push(blockquote);
            continue;
        }

        if (/^(-|\*)\s+/.test(trimmed)) {
            const ul = document.createElement('ul');
            while (i < lines.length && /^(-|\*)\s+/.test(lines[i].trim())) {
                const li = document.createElement('li');
                li.innerHTML = formatInline(lines[i].trim().replace(/^(-|\*)\s+/, ''));
                ul.appendChild(li);
                i += 1;
            }
            blocks.push(ul);
            continue;
        }

        if (/^\d+\.\s+/.test(trimmed)) {
            const ol = document.createElement('ol');
            while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
                const li = document.createElement('li');
                li.innerHTML = formatInline(lines[i].trim().replace(/^\d+\.\s+/, ''));
                ol.appendChild(li);
                i += 1;
            }
            blocks.push(ol);
            continue;
        }

        if (/^---+$/.test(trimmed)) {
            blocks.push(document.createElement('hr'));
            i += 1;
            continue;
        }

        const paragraphLines = [];
        while (
            i < lines.length &&
            lines[i].trim() &&
            !/^#{1,6}\s+/.test(lines[i].trim()) &&
            !/^>\s?/.test(lines[i].trim()) &&
            !/^(-|\*)\s+/.test(lines[i].trim()) &&
            !/^\d+\.\s+/.test(lines[i].trim()) &&
            !/^```/.test(lines[i].trim()) &&
            !/^---+$/.test(lines[i].trim())
        ) {
            paragraphLines.push(lines[i].trim());
            i += 1;
        }

        const p = document.createElement('p');
        p.innerHTML = formatInline(paragraphLines.join(' '));
        blocks.push(p);
    }

    return blocks;
}

// Function to simulate typing effect with richer text formatting
async function typeMessage(element, paragraphs) {
    const blocks = renderMarkdownBlocks(paragraphs.join('\n\n'));
    for (let i = 0; i < blocks.length; i++) {
        element.appendChild(blocks[i]);
        await new Promise(resolve => setTimeout(resolve, 220));
    }
}

// Submit message on Enter key press
document.getElementById('user-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
