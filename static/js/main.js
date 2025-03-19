document.addEventListener("DOMContentLoaded", () => {
    // Add animation classes to elements
    const animatedElements = document.querySelectorAll(".glass-card, .route-card, .dashboard-card")
    animatedElements.forEach((element, index) => {
      element.style.animationDelay = `${index * 0.1}s`
      element.classList.add("animate-fade-in")
    })
  
    // Initialize tooltips if any
    const tooltips = document.querySelectorAll("[data-tooltip]")
    tooltips.forEach((tooltip) => {
      tooltip.addEventListener("mouseenter", function () {
        const tooltipText = this.getAttribute("data-tooltip")
        const tooltipEl = document.createElement("div")
        tooltipEl.className = "tooltip"
        tooltipEl.textContent = tooltipText
        document.body.appendChild(tooltipEl)
  
        const rect = this.getBoundingClientRect()
        tooltipEl.style.top = `${rect.top - tooltipEl.offsetHeight - 10}px`
        tooltipEl.style.left = `${rect.left + (rect.width / 2) - tooltipEl.offsetWidth / 2}px`
        tooltipEl.style.opacity = "1"
      })
  
      tooltip.addEventListener("mouseleave", () => {
        const tooltipEl = document.querySelector(".tooltip")
        if (tooltipEl) {
          tooltipEl.remove()
        }
      })
    })
  
    // Add smooth scrolling to all links
    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
      anchor.addEventListener("click", function (e) {
        e.preventDefault()
  
        document.querySelector(this.getAttribute("href")).scrollIntoView({
          behavior: "smooth",
        })
      })
    })
  })
  
  // Function to show a notification
  function showNotification(message, type = "info") {
    const notification = document.createElement("div")
    notification.className = `notification notification-${type}`
    notification.textContent = message
  
    document.body.appendChild(notification)
  
    setTimeout(() => {
      notification.classList.add("show")
    }, 10)
  
    setTimeout(() => {
      notification.classList.remove("show")
      setTimeout(() => {
        notification.remove()
      }, 300)
    }, 3000)
  }
  
  // Function to toggle password visibility
  function togglePasswordVisibility(inputId, iconId) {
    const passwordInput = document.getElementById(inputId)
    const icon = document.getElementById(iconId)
  
    if (passwordInput.type === "password") {
      passwordInput.type = "text"
      icon.className = "fas fa-eye-slash"
    } else {
      passwordInput.type = "password"
      icon.className = "fas fa-eye"
    }
  }
  
  