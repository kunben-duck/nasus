/**
 * AutoTest AI - Shared JavaScript Utilities
 * Global functions and classes for all pages
 */

// ========================================
// LUCIDE ICONS INITIALIZATION
// ========================================

/**
 * Initialize Lucide icons on the page
 * Call this after DOM updates that add new icons
 */
function initIcons() {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

// Auto-initialize icons when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  initIcons();
});

// ========================================
// PARTICLE BACKGROUND (Three.js)
// ========================================

class ParticleBackground {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    if (!this.container) {
      console.warn(`Particle container #${containerId} not found`);
      return;
    }

    // Default configuration
    this.config = {
      count: 80,
      color: '#00d4ff',
      secondaryColor: '#7c3aed',
      size: { min: 1, max: 3 },
      speed: { min: 0.2, max: 0.8 },
      opacity: { min: 0.3, max: 0.8 },
      connectionDistance: 150,
      connectionOpacity: 0.15,
      mouseRadius: 200,
      mouseForce: 0.02,
      ...options
    };

    this.particles = [];
    this.mouse = { x: null, y: null };
    this.animationId = null;

    this.init();
  }

  init() {
    // Create canvas
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'particle-canvas';
    this.canvas.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 0;
    `;
    this.container.appendChild(this.canvas);

    this.ctx = this.canvas.getContext('2d');
    this.resize();

    // Create particles
    this.createParticles();

    // Event listeners
    window.addEventListener('resize', () => this.resize());
    window.addEventListener('mousemove', (e) => this.handleMouseMove(e));
    window.addEventListener('mouseleave', () => this.handleMouseLeave());

    // Start animation
    this.animate();
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  createParticles() {
    this.particles = [];
    for (let i = 0; i < this.config.count; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        vx: (Math.random() - 0.5) * this.config.speed.max * 2,
        vy: (Math.random() - 0.5) * this.config.speed.max * 2,
        size: this.config.size.min + Math.random() * (this.config.size.max - this.config.size.min),
        opacity: this.config.opacity.min + Math.random() * (this.config.opacity.max - this.config.opacity.min),
        color: Math.random() > 0.5 ? this.config.color : this.config.secondaryColor
      });
    }
  }

  handleMouseMove(e) {
    this.mouse.x = e.clientX;
    this.mouse.y = e.clientY;
  }

  handleMouseLeave() {
    this.mouse.x = null;
    this.mouse.y = null;
  }

  animate() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // Update and draw particles
    this.particles.forEach((particle, i) => {
      // Mouse interaction
      if (this.mouse.x !== null && this.mouse.y !== null) {
        const dx = this.mouse.x - particle.x;
        const dy = this.mouse.y - particle.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < this.config.mouseRadius) {
          const force = (this.config.mouseRadius - distance) / this.config.mouseRadius;
          particle.vx += dx * force * this.config.mouseForce;
          particle.vy += dy * force * this.config.mouseForce;
        }
      }

      // Update position
      particle.x += particle.vx;
      particle.y += particle.vy;

      // Boundary check
      if (particle.x < 0 || particle.x > this.canvas.width) particle.vx *= -1;
      if (particle.y < 0 || particle.y > this.canvas.height) particle.vy *= -1;

      // Speed limit
      const speed = Math.sqrt(particle.vx * particle.vx + particle.vy * particle.vy);
      if (speed > this.config.speed.max) {
        particle.vx = (particle.vx / speed) * this.config.speed.max;
        particle.vy = (particle.vy / speed) * this.config.speed.max;
      }

      // Draw particle
      this.ctx.beginPath();
      this.ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      this.ctx.fillStyle = particle.color;
      this.ctx.globalAlpha = particle.opacity;
      this.ctx.fill();

      // Draw connections
      for (let j = i + 1; j < this.particles.length; j++) {
        const other = this.particles[j];
        const dx = particle.x - other.x;
        const dy = particle.y - other.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < this.config.connectionDistance) {
          this.ctx.beginPath();
          this.ctx.moveTo(particle.x, particle.y);
          this.ctx.lineTo(other.x, other.y);
          this.ctx.strokeStyle = this.config.color;
          this.ctx.globalAlpha = this.config.connectionOpacity * (1 - distance / this.config.connectionDistance);
          this.ctx.stroke();
        }
      }
    });

    this.ctx.globalAlpha = 1;
    this.animationId = requestAnimationFrame(() => this.animate());
  }

  destroy() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
    }
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas);
    }
  }
}

// ========================================
// TOAST NOTIFICATION SYSTEM
// ========================================

class ToastManager {
  constructor() {
    this.container = null;
    this.toasts = [];
    this.init();
  }

  init() {
    // Create toast container if not exists
    this.container = document.getElementById('toast-container');
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = 'toast-container';
      this.container.className = 'toast-container';
      document.body.appendChild(this.container);
    }
  }

  /**
   * Show a toast notification
   * @param {string} type - 'success', 'error', 'warning', 'info'
   * @param {string} message - Toast message
   * @param {object} options - Additional options
   */
  show(type, message, options = {}) {
    const {
      duration = 4000,
      title = null,
      closable = true
    } = options;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const iconMap = {
      success: 'check-circle',
      error: 'x-circle',
      warning: 'alert-triangle',
      info: 'info'
    };

    const titleText = title || {
      success: '成功',
      error: '错误',
      warning: '警告',
      info: '提示'
    }[type];

    toast.innerHTML = `
      <i data-lucide="${iconMap[type]}" class="toast-icon text-${this.getColorClass(type)}"></i>
      <div class="toast-content">
        <div class="toast-title">${titleText}</div>
        <div class="toast-message">${message}</div>
      </div>
      ${closable ? `
        <button class="toast-close" onclick="toastManager.dismiss(this.parentElement)">
          <i data-lucide="x" class="w-4 h-4"></i>
        </button>
      ` : ''}
    `;

    this.container.appendChild(toast);
    initIcons();

    // Auto dismiss
    if (duration > 0) {
      setTimeout(() => {
        this.dismiss(toast);
      }, duration);
    }

    return toast;
  }

  dismiss(toast) {
    if (!toast || toast.classList.contains('hiding')) return;

    toast.classList.add('hiding');
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 300);
  }

  getColorClass(type) {
    const colorMap = {
      success: 'green-400',
      error: 'red-400',
      warning: 'yellow-400',
      info: 'cyan-400'
    };
    return colorMap[type];
  }

  // Convenience methods
  success(message, options) {
    return this.show('success', message, options);
  }

  error(message, options) {
    return this.show('error', message, options);
  }

  warning(message, options) {
    return this.show('warning', message, options);
  }

  info(message, options) {
    return this.show('info', message, options);
  }
}

// Global toast manager instance
const toastManager = new ToastManager();

// Convenience function for showing toasts
function showToast(type, message, options) {
  return toastManager.show(type, message, options);
}

// ========================================
// MODAL UTILITIES
// ========================================

class ModalManager {
  constructor() {
    this.activeModal = null;
    this.overlay = null;
  }

  /**
   * Show a modal
   * @param {object} options - Modal options
   * @param {string} options.title - Modal title
   * @param {string} options.content - Modal content (HTML)
   * @param {string} options.size - 'sm', 'md', 'lg', 'xl', 'full'
   * @param {array} options.buttons - Array of button configs
   * @param {function} options.onClose - Callback when modal closes
   * @param {boolean} options.closable - Whether modal can be closed
   */
  show(options) {
    const {
      title = '',
      content = '',
      size = 'md',
      buttons = [],
      onClose = null,
      closable = true
    } = options;

    // Size classes
    const sizeClasses = {
      sm: 'max-w-md',
      md: 'max-w-lg',
      lg: 'max-w-2xl',
      xl: 'max-w-4xl',
      full: 'max-w-[90vw]'
    };

    // Create overlay
    this.overlay = document.createElement('div');
    this.overlay.className = 'modal-overlay active';
    this.overlay.innerHTML = `
      <div class="modal ${sizeClasses[size] || sizeClasses.md}">
        <div class="modal-header">
          <h3 class="modal-title">${title}</h3>
          ${closable ? `
            <button class="modal-close" onclick="modalManager.close()">
              <i data-lucide="x" class="w-5 h-5"></i>
            </button>
          ` : ''}
        </div>
        <div class="modal-body">
          ${content}
        </div>
        ${buttons.length > 0 ? `
          <div class="modal-footer">
            ${buttons.map(btn => `
              <button class="btn ${btn.class || 'btn-secondary'}" onclick="${btn.onClick || 'modalManager.close()'}">
                ${btn.icon ? `<i data-lucide="${btn.icon}" class="w-4 h-4"></i>` : ''}
                ${btn.text}
              </button>
            `).join('')}
          </div>
        ` : ''}
      </div>
    `;

    // Close on overlay click
    if (closable) {
      this.overlay.addEventListener('click', (e) => {
        if (e.target === this.overlay) {
          this.close();
        }
      });
    }

    // Close on Escape key
    if (closable) {
      this.handleEscape = (e) => {
        if (e.key === 'Escape') {
          this.close();
        }
      };
      document.addEventListener('keydown', this.handleEscape);
    }

    this.onCloseCallback = onClose;
    document.body.appendChild(this.overlay);
    initIcons();

    // Prevent body scroll
    document.body.style.overflow = 'hidden';

    return this.overlay;
  }

  close() {
    if (this.overlay) {
      this.overlay.classList.remove('active');
      setTimeout(() => {
        if (this.overlay && this.overlay.parentNode) {
          this.overlay.parentNode.removeChild(this.overlay);
        }
        this.overlay = null;
      }, 300);
    }

    if (this.handleEscape) {
      document.removeEventListener('keydown', this.handleEscape);
      this.handleEscape = null;
    }

    document.body.style.overflow = '';

    if (this.onCloseCallback) {
      this.onCloseCallback();
      this.onCloseCallback = null;
    }
  }

  /**
   * Show a confirmation dialog
   * @param {string} message - Confirmation message
   * @param {function} onConfirm - Callback when confirmed
   * @param {function} onCancel - Callback when cancelled
   */
  confirm(message, onConfirm, onCancel = null) {
    this.show({
      title: '确认操作',
      content: `<p class="text-gray-300">${message}</p>`,
      size: 'sm',
      buttons: [
        {
          text: '取消',
          class: 'btn-secondary',
          onClick: 'modalManager.close(); ' + (onCancel ? 'setTimeout(() => { (' + onCancel.toString() + ')(); }, 300)' : '')
        },
        {
          text: '确认',
          class: 'btn-primary',
          icon: 'check',
          onClick: 'modalManager.close(); setTimeout(() => { (' + onConfirm.toString() + ')(); }, 300)'
        }
      ]
    });
  }

  /**
   * Show an alert dialog
   * @param {string} message - Alert message
   * @param {string} title - Alert title
   */
  alert(message, title = '提示') {
    this.show({
      title: title,
      content: `<p class="text-gray-300">${message}</p>`,
      size: 'sm',
      buttons: [
        {
          text: '确定',
          class: 'btn-primary',
          onClick: 'modalManager.close()'
        }
      ]
    });
  }
}

// Global modal manager instance
const modalManager = new ModalManager();

// Convenience function for showing modals
function showModal(options) {
  return modalManager.show(options);
}

// ========================================
// FORMATTING UTILITIES
// ========================================

const FormatUtils = {
  /**
   * Format a date
   * @param {Date|string|number} date - Date to format
   * @param {string} format - Format pattern
   * @returns {string} Formatted date string
   */
  date(date, format = 'yyyy-MM-dd HH:mm') {
    if (!date) return '-';
    
    const d = new Date(date);
    if (isNaN(d.getTime())) return '-';

    const pad = (n) => n.toString().padStart(2, '0');

    const replacements = {
      'yyyy': d.getFullYear(),
      'MM': pad(d.getMonth() + 1),
      'dd': pad(d.getDate()),
      'HH': pad(d.getHours()),
      'mm': pad(d.getMinutes()),
      'ss': pad(d.getSeconds()),
    };

    return format.replace(/yyyy|MM|dd|HH|mm|ss/g, match => replacements[match]);
  },

  /**
   * Format date as relative time (e.g., "2小时前")
   * @param {Date|string|number} date - Date to format
   * @returns {string} Relative time string
   */
  relativeTime(date) {
    if (!date) return '-';

    const d = new Date(date);
    if (isNaN(d.getTime())) return '-';

    const now = new Date();
    const diff = now - d;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (seconds < 60) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;
    if (days < 7) return `${days}天前`;
    if (days < 30) return `${Math.floor(days / 7)}周前`;
    if (days < 365) return `${Math.floor(days / 30)}个月前`;
    return `${Math.floor(days / 365)}年前`;
  },

  /**
   * Format a number with commas
   * @param {number} num - Number to format
   * @returns {string} Formatted number string
   */
  number(num) {
    if (num === null || num === undefined) return '-';
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  },

  /**
   * Format a percentage
   * @param {number} value - Value to format (0-1 or 0-100)
   * @param {number} decimals - Number of decimal places
   * @returns {string} Formatted percentage string
   */
  percent(value, decimals = 1) {
    if (value === null || value === undefined) return '-';
    const normalized = value > 1 ? value : value * 100;
    return normalized.toFixed(decimals) + '%';
  },

  /**
   * Format duration in milliseconds
   * @param {number} ms - Duration in milliseconds
   * @returns {string} Formatted duration string
   */
  duration(ms) {
    if (!ms || ms < 0) return '-';

    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
      return `${hours}小时 ${minutes % 60}分钟`;
    }
    if (minutes > 0) {
      return `${minutes}分钟 ${seconds % 60}秒`;
    }
    return `${seconds}秒`;
  },

  /**
   * Format file size
   * @param {number} bytes - Size in bytes
   * @returns {string} Formatted file size
   */
  fileSize(bytes) {
    if (!bytes || bytes < 0) return '-';

    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = bytes;
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }

    return `${size.toFixed(2)} ${units[unitIndex]}`;
  },

  /**
   * Truncate text with ellipsis
   * @param {string} text - Text to truncate
   * @param {number} maxLength - Maximum length
   * @returns {string} Truncated text
   */
  truncate(text, maxLength = 100) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }
};

// ========================================
// UTILITY FUNCTIONS
// ========================================

/**
 * Debounce a function
 * @param {function} func - Function to debounce
 * @param {number} wait - Wait time in milliseconds
 * @returns {function} Debounced function
 */
function debounce(func, wait = 300) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle a function
 * @param {function} func - Function to throttle
 * @param {number} limit - Limit time in milliseconds
 * @returns {function} Throttled function
 */
function throttle(func, limit = 300) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

/**
 * Generate a unique ID
 * @param {string} prefix - ID prefix
 * @returns {string} Unique ID
 */
function generateId(prefix = 'id') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Copy text to clipboard
 * @param {string} text - Text to copy
 * @returns {Promise<boolean>} Success status
 */
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('success', '已复制到剪贴板');
    return true;
  } catch (err) {
    showToast('error', '复制失败');
    return false;
  }
}

/**
 * Download data as a file
 * @param {string} data - Data to download
 * @param {string} filename - File name
 * @param {string} type - MIME type
 */
function downloadFile(data, filename, type = 'text/plain') {
  const blob = new Blob([data], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Animate a number counting up
 * @param {HTMLElement} element - Element to animate
 * @param {number} target - Target number
 * @param {number} duration - Animation duration in ms
 * @param {string} suffix - Suffix to add (e.g., '%')
 */
function animateNumber(element, target, duration = 1500, suffix = '') {
  const start = 0;
  const startTime = performance.now();

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    
    // Easing function (ease-out)
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const current = Math.floor(start + (target - start) * easeOut);
    
    element.textContent = FormatUtils.number(current) + suffix;

    if (progress < 1) {
      requestAnimationFrame(update);
    }
  }

  requestAnimationFrame(update);
}

/**
 * Check if element is in viewport
 * @param {HTMLElement} element - Element to check
 * @returns {boolean} Whether element is in viewport
 */
function isInViewport(element) {
  const rect = element.getBoundingClientRect();
  return (
    rect.top >= 0 &&
    rect.left >= 0 &&
    rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
    rect.right <= (window.innerWidth || document.documentElement.clientWidth)
  );
}

/**
 * Intersection Observer helper
 * @param {string} selector - Element selector
 * @param {function} callback - Callback when element enters viewport
 * @param {object} options - Observer options
 */
function onElementVisible(selector, callback, options = {}) {
  const elements = document.querySelectorAll(selector);
  
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        callback(entry.target);
        if (options.once) {
          observer.unobserve(entry.target);
        }
      }
    });
  }, {
    threshold: options.threshold || 0.1,
    rootMargin: options.rootMargin || '0px'
  });

  elements.forEach(el => observer.observe(el));
  return observer;
}

// ========================================
// DATA STORAGE UTILITIES
// ========================================

const Storage = {
  /**
   * Set item in localStorage
   * @param {string} key - Storage key
   * @param {*} value - Value to store
   */
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      console.error('Storage set error:', e);
    }
  },

  /**
   * Get item from localStorage
   * @param {string} key - Storage key
   * @param {*} defaultValue - Default value if not found
   * @returns {*} Stored value
   */
  get(key, defaultValue = null) {
    try {
      const item = localStorage.getItem(key);
      return item ? JSON.parse(item) : defaultValue;
    } catch (e) {
      console.error('Storage get error:', e);
      return defaultValue;
    }
  },

  /**
   * Remove item from localStorage
   * @param {string} key - Storage key
   */
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      console.error('Storage remove error:', e);
    }
  },

  /**
   * Clear all localStorage
   */
  clear() {
    try {
      localStorage.clear();
    } catch (e) {
      console.error('Storage clear error:', e);
    }
  }
};

// ========================================
// API UTILITIES
// ========================================

const API = {
  baseURL: '',

  /**
   * Set API base URL
   * @param {string} url - Base URL
   */
  setBaseURL(url) {
    this.baseURL = url;
  },

  /**
   * Make an API request
   * @param {string} endpoint - API endpoint
   * @param {object} options - Request options
   * @returns {Promise} Response promise
   */
  async request(endpoint, options = {}) {
    const url = this.baseURL + endpoint;
    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      },
      ...options
    };

    if (config.body && typeof config.body === 'object') {
      config.body = JSON.stringify(config.body);
    }

    try {
      const response = await fetch(url, config);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('API request error:', error);
      throw error;
    }
  },

  /**
   * GET request
   * @param {string} endpoint - API endpoint
   * @param {object} params - Query parameters
   * @returns {Promise} Response promise
   */
  get(endpoint, params = {}) {
    const queryString = new URLSearchParams(params).toString();
    const url = queryString ? `${endpoint}?${queryString}` : endpoint;
    return this.request(url, { method: 'GET' });
  },

  /**
   * POST request
   * @param {string} endpoint - API endpoint
   * @param {object} data - Request body
   * @returns {Promise} Response promise
   */
  post(endpoint, data = {}) {
    return this.request(endpoint, { method: 'POST', body: data });
  },

  /**
   * PUT request
   * @param {string} endpoint - API endpoint
   * @param {object} data - Request body
   * @returns {Promise} Response promise
   */
  put(endpoint, data = {}) {
    return this.request(endpoint, { method: 'PUT', body: data });
  },

  /**
   * DELETE request
   * @param {string} endpoint - API endpoint
   * @returns {Promise} Response promise
   */
  delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  }
};

// ========================================
// INITIALIZATION
// ========================================

document.addEventListener('DOMContentLoaded', function() {
  // Initialize particle background if container exists
  const particleContainer = document.getElementById('particle-container');
  if (particleContainer && typeof THREE !== 'undefined') {
    window.particleBackground = new ParticleBackground('particle-container');
  }

  // Initialize tooltips
  document.querySelectorAll('[data-tooltip]').forEach(el => {
    el.classList.add('tooltip');
  });
});

// Export utilities for use in other scripts
window.AutoTestAI = {
  ParticleBackground,
  toastManager,
  modalManager,
  FormatUtils,
  Storage,
  API,
  debounce,
  throttle,
  generateId,
  copyToClipboard,
  downloadFile,
  animateNumber,
  isInViewport,
  onElementVisible,
  showToast,
  showModal
};
