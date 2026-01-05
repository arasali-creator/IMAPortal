let currentStep = 0;
showStep(currentStep);

function showStep(n) {
  let steps = document.getElementsByClassName("form-step");
  steps[n].style.display = "block";

  // Handle buttons
  if (n === 0) {
    document.getElementById("prevBtn").style.display = "none";
  } else {
    document.getElementById("prevBtn").style.display = "inline";
  }

  if (n === (steps.length - 1)) {
    document.getElementById("nextBtn").innerHTML = "Submit";
  } else {
    document.getElementById("nextBtn").innerHTML = "Next";
  }
}

function nextPrev(n) {
  let steps = document.getElementsByClassName("form-step");

  // Hide current step
  steps[currentStep].style.display = "none";

  // Change step
  currentStep += n;

  // If at the end, submit
  if (currentStep >= steps.length) {
    document.getElementById("regForm").submit();
    return false;
  }

  // Show next step
  showStep(currentStep);
}
