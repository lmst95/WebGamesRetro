const burger = document.getElementById("burger");
const navMenu = document.getElementById("navMenu");

if (burger && navMenu) {
  burger.addEventListener("click", () => {
    const isOpen = navMenu.classList.toggle("open");
    burger.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  navMenu.addEventListener("click", (event) => {
    if (event.target.tagName === "A") {
      navMenu.classList.remove("open");
      burger.setAttribute("aria-expanded", "false");
    }
  });
}
