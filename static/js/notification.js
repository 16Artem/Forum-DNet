function showNotification(message, type) {
    const container = document.getElementById('notification-container');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;

    const icons = {
        'success': 'fas fa-check-circle',
        'error': 'fas fa-exclamation-circle',
        'info': 'fas fa-info-circle'
    };

    notification.innerHTML = `
        <i class="${icons[type] || icons['info']}"></i>
        <span>${message}</span>
    `;

    container.appendChild(notification);

    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

// Для автоматического закрытия при клике
document.addEventListener('click', function(e) {
    if (e.target.closest('.notification')) {
        e.target.closest('.notification').remove();
    }
});