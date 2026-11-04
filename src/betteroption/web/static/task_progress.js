(() => {
  "use strict";

  const taskProgress = document.querySelector("[data-task-progress]");
  if (!taskProgress) return;

  // Deliberately local copy: no provider or LLM call is needed just to make a
  // long wait feel human. Keep each line short enough for the progress card.
  const COMMON_WAITING_COPY = [
    "A little patience, a better shortlist.",
    "Good time to grab a coffee.",
    "Tea is equally compatible with this workflow.",
    "You can leave this page while the work keeps going.",
    "The progress bar gets shy when stared at.",
    "A short screen break is fully supported.",
    "The careful part takes a moment.",
    "Slow enough to check, quick enough to stay useful.",
    "Still working at a pleasantly undramatic pace.",
    "Your browser is not doing the heavy lifting here.",
    "This is a background task, not a staring contest.",
    "The progress bar appreciates your patience.",
    "A stretch break would fit nicely here.",
    "Fresh air remains compatible with job searching.",
    "You are allowed to do something nicer for a minute.",
    "The workflow continues even when this tab is quiet.",
    "Feel free to explore elsewhere while this task keeps running.",
    "One careful pass is better than three frantic ones.",
    "We are keeping the busywork in the background.",
    "This part is intentionally unhurried.",
    "A calm search can still cover plenty of ground.",
    "The refresh button may enjoy a well-earned rest.",
    "The task is stored safely while it runs.",
    "A second tab will not make this twice as fast.",
    "Consider this your official hydration reminder.",
    "The repetitive part has found its natural habitat.",
    "You keep the judgment while the task handles the waiting.",
    "Small pause, useful result.",
    "The spinner is working on its portfolio.",
    "This workflow has not forgotten about you.",
    "Background work is less glamorous and rather useful.",
    "The bar can look thoughtful while progress continues.",
    "Results will be waiting when the task finishes.",
    "Move around the app if you like while this task keeps its place.",
    "A moment of patience is currently the only requirement.",
    "Nothing is stuck merely because it is quiet.",
    "Some checks are better measured in minutes than clicks.",
    "The tab may rest while the task carries on.",
    "Come back whenever you like and the result will wait here.",
    "No ceremonial button press is needed.",
    "A tiny intermission for a less tiny workflow.",
    "The progress bar is an estimate, not a promise to race.",
    "Careful work is happening behind this very calm page.",
    "The workflow is taking the scenic route through the data.",
    "Still here and still checking.",
    "Your future self may appreciate this patient minute.",
    "A quieter interface leaves more room for better decisions.",
    "This is a fine moment to look away from a screen.",
    "The useful result matters more than an exciting loading screen.",
    "Everything needed is already in motion.",
    "A break might make the next decision easier.",
    "Feel free to check whether the outside still exists.",
    "A window view counts as a tiny change of scenery.",
    "You can come back with fresh eyes and the task will not mind.",
    "This minute does not need to become productive.",
    "Background workflows are excellent at waiting for themselves.",
    "No hidden quiz will appear while this runs.",
    "The data is busy enough for both of you.",
    "A thoughtful pause is still progress of a sort.",
    "Meanwhile, the rest of the app is still yours to explore.",
    "You may safely ignore the spinner for a while.",
    "A calm interface cannot shorten the work, but it can improve the wait.",
    "The browser tab is keeping your place.",
    "This is permission to refill your water.",
    "A few shoulder rolls are cheaper than an ergonomic chair review.",
    "No result improves when watched continuously.",
    "The workflow knows where it left off.",
    "A little distance from the screen can be useful too.",
    "The final judgment remains yours because software can miss things.",
    "Technical work is happening without requiring technical staring.",
    "The task has enough instructions for now.",
    "There is no bonus for staying on this exact tab.",
    "The queue is patient, even if browsers are dramatic.",
    "Let the background have the foreground for a moment.",
    "The calm part of the workflow is working as designed.",
    "One less thing to hold in your head for a minute.",
    "The next page will have more useful things to judge.",
    "A short pause can be part of a good search.",
    "The task can handle a minute without supervision.",
    "Still processing, with no urgency theatre required.",
  ];

  const EXPLORE_WAITING_COPY = [
    "Looking beyond the loudest job boards.",
    "Checking a few quieter corners of the job market.",
    "Public feeds first, useful roles next.",
    "Comparing sources before ranking their results.",
    "A broad search now can save narrow scrolling later.",
    "Hunting for signal in a rather noisy market.",
    "Job titles remain impressively inconsistent.",
    "Looking past creative titles for the actual work.",
    "Some good roles hide behind remarkably odd wording.",
    "Checking employer boards as well as public feeds.",
    "Gathering candidates before making local comparisons.",
    "Distance and relevance will get their turn.",
    "The providers are searching before local ranking begins.",
    "More sources, one calmer shortlist.",
    "Scanning broadly without asking you to scroll broadly.",
    "Not every result deserves a place near the top.",
    "Fresh roles and durable links are getting extra attention.",
    "Looking for jobs, not just pages containing job-shaped words.",
    "Employer boards can be shy around search engines.",
    "The internet has many vacancies and several opinions about titles.",
    "Duplicate listings are being politely introduced to each other.",
    "A familiar role may be wearing an unfamiliar title.",
    "Checking whether promising links still lead somewhere useful.",
    "Separating actual openings from enthusiastic search-engine debris.",
    "The wide search will become a more selective final list.",
    "A nearby gem can take a few sources to surface.",
    "Looking for the role behind the keyword.",
    "The public web is answering a few polite questions.",
    "Collecting enough options to make ranking meaningful.",
    "The shortlist is earning its name.",
    "Still checking roles near {location}.",
    "Looking a little deeper around {location}.",
    "Keeping {location} in view while the search expands.",
    "Comparing nearby options around {location}.",
    "Searching beyond the obvious boards near {location}.",
    "Looking for useful local signal around {location}.",
    "The search radius around {location} is doing real work.",
    "Still exploring the job market around {location}.",
    "Checking whether strong roles near {location} use unexpected titles.",
    "Giving employer boards around {location} another careful look.",
    "Local relevance around {location} comes before alphabetical luck.",
    "Keeping remote roles separate from the distance math.",
    "Rough distance comes first while exact routes wait for Matching.",
    "Searching in parallel and ranking together.",
    "Different providers speak different dialects of job search.",
    "A provider returning zero can still be an honest result.",
    "The source count is not the same thing as the useful-job count.",
    "Checking dates where the source actually provides one.",
    "Older listings are being treated with healthy suspicion.",
    "Fresh does not always mean relevant but it certainly helps.",
    "A vacancy can hide three jobs behind one ambitious title.",
    "Three different titles can still describe the same Tuesday morning.",
    "Recruitment dialect is being translated into ordinary language.",
    "Some listings contain enough bullets to qualify as stationery.",
    "Remote roles still live somewhere on a map.",
    "The best keyword is sometimes the one the employer forgot to use.",
    "Search portals are not being mistaken for individual jobs.",
  ];

  const MATCH_WAITING_COPY = [
    "Comparing the job with your Compass, not with a generic applicant.",
    "Turning job-posting prose into something easier to judge.",
    "Checking strengths, trade-offs and possible dealbreakers.",
    "A compatibility score should explain itself.",
    "Evidence first, confident adjectives later.",
    "Looking for fit without pretending every unknown is a positive.",
    "Your preferences are doing more than decorating the profile.",
    "Comparing what the role says with what you actually want.",
    "A good match can include honest uncertainties.",
    "Checking the employer and the job as separate questions.",
    "The score is only useful when the reasoning survives inspection.",
    "Strong keywords do not automatically make a strong match.",
    "Looking beyond title similarity.",
    "Skills are being compared in context, not counted like stickers.",
    "A missing detail stays missing until a source supports it.",
    "Separating confirmed facts from reasonable orientation.",
    "The Compass has opinions worth applying carefully.",
    "Checking whether the daily work fits, not merely the job family.",
    "Work arrangement and location are part of compatibility too.",
    "Salary clues are useful, but they are not clairvoyance.",
    "Employer evidence is getting its own pass.",
    "Possible blockers are being checked before the shiny parts win.",
    "The match is allowed to say that we do not know yet.",
    "A precise unknown is better than a decorative guess.",
    "Comparing role fit, seniority and practical constraints.",
    "The job description is being translated from recruitment dialect.",
    "Checking whether required skills are truly required.",
    "Nice-to-have lists are being kept in their proper place.",
    "Looking for evidence that changes the decision.",
    "Not every bullet point deserves equal weight.",
    "The final score is being assembled from smaller judgments.",
    "Matching is part analysis, part healthy skepticism.",
    "A role can be exciting and still have a practical blocker.",
    "A role can look ordinary and still fit unusually well.",
    "Checking the commute before declaring eternal compatibility.",
    "The evidence is being bundled into a readable story.",
    "Your own rating will remain allowed to disagree with the model.",
    "Numbers are helpful while your judgment keeps the last word.",
    "The score has no feelings so feel free to disagree.",
    "Trying to be useful without pretending to be certain.",
    "Checking sources before polishing conclusions.",
    "A little nerdiness is being retained for quality control.",
    "The route check may know trains better than job titles.",
    "The salary check is consulting evidence, not a crystal ball.",
    "Still building a match you can challenge and edit.",
    "Making the reasons easier to scan than the original posting.",
    "Unknowns are not being quietly promoted to facts.",
    "The final recommendation is taking shape.",
    "One more pass for contradictions and loose ends.",
    "Almost ready to hand the decision back to you.",
    "Unknown evidence is waiting to earn its promotion.",
    "A shiny title does not get diplomatic immunity from your boundaries.",
    "The job description has entered the cross-examination phase.",
    "Even dream jobs are expected to show their working.",
    "Compatibility is checking the practical details before planning a future together.",
  ];

  const normalizeCopy = (value) => (value || "")
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();

  const heading = taskProgress.querySelector("#task-title");
  const technicalStatus = taskProgress.querySelector("[data-task-technical-status]");
  const technicalMessage = taskProgress.querySelector("[data-task-message]");
  const waitingMessage = taskProgress.querySelector("[data-task-waiting-message]");
  const taskError = taskProgress.querySelector("[data-task-error]");

  const syncTechnicalStatus = () => {
    if (!heading || !technicalStatus || !technicalMessage) return;
    technicalStatus.hidden = (
      normalizeCopy(heading.textContent) === normalizeCopy(technicalMessage.textContent)
    );
  };

  if (technicalMessage) {
    new MutationObserver(syncTechnicalStatus).observe(technicalMessage, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }
  syncTechnicalStatus();

  if (!waitingMessage) return;

  const location = (taskProgress.dataset.taskLocation || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
  const kind = taskProgress.dataset.taskKind;
  const workflowCopy = kind === "explore_search" || kind === "job_import"
    ? EXPLORE_WAITING_COPY
    : MATCH_WAITING_COPY;
  const phrasePool = [...COMMON_WAITING_COPY, ...workflowCopy]
    .filter((phrase) => location || !phrase.includes("{location}"));
  let previousPhrase = "";
  let timerId;

  const randomUnit = () => {
    if (window.crypto?.getRandomValues) {
      const value = new Uint32Array(1);
      window.crypto.getRandomValues(value);
      return value[0] / 4294967296;
    }
    return Math.random();
  };
  const randomDelay = () => 24000 + Math.floor(randomUnit() * 60001);
  const renderPhrase = () => {
    if (!phrasePool.length) return;
    let phrase = phrasePool[Math.floor(randomUnit() * phrasePool.length)];
    if (phrasePool.length > 1 && phrase === previousPhrase) {
      phrase = phrasePool[(phrasePool.indexOf(phrase) + 1) % phrasePool.length];
    }
    previousPhrase = phrase;
    waitingMessage.textContent = phrase.replaceAll("{location}", location);
  };
  const scheduleNextPhrase = () => {
    timerId = window.setTimeout(() => {
      if (taskError && !taskError.hidden) {
        waitingMessage.hidden = true;
        return;
      }
      renderPhrase();
      scheduleNextPhrase();
    }, randomDelay());
  };

  renderPhrase();
  scheduleNextPhrase();
  window.addEventListener("pagehide", () => window.clearTimeout(timerId), { once: true });
})();
