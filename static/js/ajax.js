// Проверяем существование элемента перед выполнением кода
document.addEventListener('DOMContentLoaded', function() {
    const registerForm = document.getElementById('register-form');
    const loginForm = document.getElementById('login-form');
    
    // Обработка формы регистрации
    if (registerForm) {
        registerForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitForm(this);
        });
    }
    
    // Обработка формы входа
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitForm(this);
        });
    }
    
    function submitForm(form) {
        const formData = new FormData(form);
        
        // Добавляем CSRF токен
        const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
        if (csrfToken) {
            formData.append('csrf_token', csrfToken);
        }
        
        fetch(form.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken || ''
            }
        })
        .then(response => {
            if (response.redirected) {
                window.location.href = response.url;
            }
            return response.json().catch(() => ({}));
        })
        .then(data => {
            if (data.error) {
                showNotification(data.error, 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Произошла ошибка при отправке формы', 'error');
        });
    }
    
    function showNotification(message, type) {
        // Ваша реализация показа уведомлений
        alert(`${type}: ${message}`);
    }
});