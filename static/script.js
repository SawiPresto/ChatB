async function sendMessage() {
    const userInput = document.getElementById('user-input').value.trim();
    if (!userInput) return;  // Handle empty input

    const chatMessages = document.getElementById('chat-messages');
    const sendButton = document.getElementById('send-button');

    // Disable send button and change text
    sendButton.disabled = true;
    sendButton.textContent = "Typing...";

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
    typingIndicatorText.textContent = 'Typing...';
    typingIndicator.appendChild(typingIndicatorText);
    chatMessages.appendChild(typingIndicator);

    // Scroll chat container to the bottom with smooth behavior
    chatMessages.scroll({
        top: chatMessages.scrollHeight,
        behavior: 'smooth'
    });

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
                model: 'llama3-8b-8192'
            })
        });

        const data = await response.json();

        // Remove typing indicator
        chatMessages.removeChild(typingIndicator);

        // Add system message with typing effect
        const systemMessageContainer = document.createElement('div');
        systemMessageContainer.classList.add('message-container', 'system-message-container');
        const systemMessage = document.createElement('div');
        systemMessage.classList.add('system-message');
        systemMessageContainer.appendChild(systemMessage);
        chatMessages.appendChild(systemMessageContainer);

        const text = data.response;
        const paragraphs = text.split('\n\n'); // Split response into paragraphs

        // Simulate typing effect
        await typeMessage(systemMessage, paragraphs);

        // Enable send button and change text back
        sendButton.disabled = false;
        sendButton.textContent = "Send";
        sendButton.classList.remove('loading');
    } catch (error) {
        console.error('Error:', error);
        // Handle error case, possibly show an error message to the user
        // Ensure to remove the typing indicator if an error occurs
        chatMessages.removeChild(typingIndicator);

        // Enable send button and change text back
        sendButton.disabled = false;
        sendButton.textContent = "Send";
        sendButton.classList.remove('loading');
    } finally {
        // Ensure scroll is at the bottom after messages are added
        chatMessages.scroll({
            top: chatMessages.scrollHeight,
            behavior: 'smooth'
        });
    }
}

// Function to simulate typing effect
async function typeMessage(element, paragraphs) {
    for (let i = 0; i < paragraphs.length; i++) {
        const paragraph = paragraphs[i];
        let paragraphElement;

        if (paragraph.startsWith('*')) {
            // Split the bullet list items
            const listItems = paragraph.split('\n*');
            const list = document.createElement('ul');
            listItems.forEach((item) => {
                // Remove the leading '*' from each item
                item = item.substring(1).trim();
                const listItem = document.createElement('li');
                listItem.textContent = item;
                list.appendChild(listItem);
            });
            paragraphElement = list;
        } else if (paragraph.match(/^\d+\./)) {
            // Split the numbered list items
            const listItems = paragraph.split('\n');
            const list = document.createElement('ol');
            listItems.forEach((item) => {
                // Remove the number and dot from each item
                item = item.replace(/^\d+\./, '').trim();
                const listItem = document.createElement('li');
                listItem.textContent = item;
                list.appendChild(listItem);
            });
            paragraphElement = list;
        } else {
            paragraphElement = document.createElement('p');
            // Detect and format bold text
            paragraphElement.innerHTML = paragraph.trim().replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        }
        element.appendChild(paragraphElement);
        // Wait a short time before typing the next paragraph
        await new Promise(resolve => setTimeout(resolve, 500)); // Adjust typing speed here
        // Scroll chat container to bottom after adding each paragraph
        element.scrollTop = element.scrollHeight;
    }
}

// Submit message on Enter key press
document.getElementById('user-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});
