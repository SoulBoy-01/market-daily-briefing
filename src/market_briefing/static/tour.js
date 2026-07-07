(function () {
  const tour = document.querySelector("[data-tour]");
  if (!tour) {
    return;
  }

  const steps = Array.from(tour.querySelectorAll("[data-tour-step]"));
  const title = tour.querySelector("[data-tour-title]");
  const body = tour.querySelector("[data-tour-body]");
  const counter = tour.querySelector("[data-tour-counter]");
  const tourCard = tour.querySelector(".tour-card");
  const nextButton = tour.querySelector("[data-tour-next]");
  const prevButton = tour.querySelector("[data-tour-prev]");
  const skipButton = tour.querySelector("[data-tour-skip]");
  const openButtons = document.querySelectorAll("[data-tour-open]");
  const storageKey = "marketBriefingTourSeen:v1";
  let currentIndex = 0;
  let highlightedElement = null;
  let activeTarget = null;

  function clearHighlight() {
    if (highlightedElement) {
      highlightedElement.classList.remove("tour-highlight");
      highlightedElement = null;
    }
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function positionTourCard() {
    if (tour.hidden || !activeTarget || !tourCard) {
      return;
    }

    const spacing = 16;
    const targetRect = activeTarget.getBoundingClientRect();
    const cardRect = tourCard.getBoundingClientRect();
    const maxTop = window.innerHeight - cardRect.height - spacing;
    const maxLeft = window.innerWidth - cardRect.width - spacing;
    const top = clamp(targetRect.top + spacing, spacing, maxTop);
    const left = clamp(targetRect.right - cardRect.width - spacing, spacing, maxLeft);

    tourCard.style.top = `${top}px`;
    tourCard.style.left = `${left}px`;
    tourCard.style.transform = "none";
  }

  function showStep(index) {
    currentIndex = Math.max(0, Math.min(index, steps.length - 1));
    const step = steps[currentIndex];
    title.textContent = step.dataset.tourTitle;
    body.textContent = step.dataset.tourBody;
    counter.textContent = `${currentIndex + 1}/${steps.length}`;
    prevButton.disabled = currentIndex === 0;
    nextButton.textContent = currentIndex === steps.length - 1 ? "完成" : "下一步";

    clearHighlight();
    const target = document.getElementById(step.dataset.tourTarget);
    if (target) {
      activeTarget = target;
      highlightedElement = target;
      highlightedElement.classList.add("tour-highlight");
      highlightedElement.scrollIntoView({ block: "center", behavior: "smooth" });
      positionTourCard();
      window.requestAnimationFrame(positionTourCard);
    } else {
      activeTarget = null;
    }
  }

  function openTour() {
    if (!steps.length) {
      return;
    }
    tour.hidden = false;
    document.body.classList.add("tour-active");
    showStep(0);
  }

  function closeTour() {
    tour.hidden = true;
    document.body.classList.remove("tour-active");
    clearHighlight();
    activeTarget = null;
    window.localStorage.setItem(storageKey, "true");
  }

  function completeTour() {
    closeTour();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  nextButton.addEventListener("click", function () {
    if (currentIndex === steps.length - 1) {
      completeTour();
      return;
    }
    showStep(currentIndex + 1);
  });

  prevButton.addEventListener("click", function () {
    showStep(currentIndex - 1);
  });

  skipButton.addEventListener("click", closeTour);

  openButtons.forEach(function (button) {
    button.addEventListener("click", openTour);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !tour.hidden) {
      closeTour();
    }
  });

  window.addEventListener("scroll", positionTourCard, { passive: true });
  window.addEventListener("resize", positionTourCard);

  if (!window.localStorage.getItem(storageKey)) {
    openTour();
  }
})();
