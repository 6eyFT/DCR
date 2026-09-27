"use strict";
const audio = document.querySelector("#audio");
const tune = document.querySelector("#tune");
const volume = document.querySelector("#volume");
const status = document.querySelector("#play-status");
let wanted = false;
let stationLive = false;
let retry;
let stationId;
let attempt = 0;
let connecting = false;

try { volume.value = localStorage.getItem("dcr-volume") ?? "70"; } catch {}
function setVolume() {
  audio.volume = Math.max(0, Math.min(1, Number(volume.value) / 100));
  document.querySelector("#volume-value").value = `${volume.value}%`;
  try { localStorage.setItem("dcr-volume", volume.value); } catch {}
}
setVolume();
volume.addEventListener("input", setVolume);

function release() {
  clearTimeout(retry);
  attempt++;
  connecting = false;
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  document.body.classList.remove("listening");
}

async function joinLive() {
  release();
  if (!wanted || !stationLive) return;
  const thisAttempt = attempt;
  connecting = true;
  tune.textContent = "Pause";
  status.textContent = "Tuning in to the live broadcast…";
  audio.src = `/stream?connection=${Date.now()}`;
  try {
    await audio.play();
    if (thisAttempt !== attempt) return;
    connecting = false;
    document.body.classList.add("listening");
    status.textContent = "Listening live. Shared broadcast; a short playback delay is normal.";
  } catch (error) {
    if (thisAttempt !== attempt) return;
    connecting = false;
    if (error.name === "NotAllowedError") {
      wanted = false;
      release();
      tune.textContent = "Tune In";
      status.textContent = "Your browser needs a click. Select Tune In to listen.";
    } else reconnect();
  }
}

function reconnect() {
  release();
  if (wanted && stationLive) {
    status.textContent = "Signal interrupted. Reconnecting to the live broadcast…";
    retry = setTimeout(joinLive, 2000);
  }
}

tune.addEventListener("click", () => {
  wanted = !wanted;
  if (wanted) joinLive();
  else {
    release();
    tune.textContent = "Tune In";
    status.textContent = stationLive ? "Paused on this device. The station is still broadcasting." : "Playback stopped. Waiting for the station.";
  }
});
audio.addEventListener("error", () => { if (wanted && audio.hasAttribute("src")) reconnect(); });
audio.addEventListener("ended", reconnect);
audio.addEventListener("stalled", reconnect);
window.addEventListener("online", () => { if (wanted) joinLive(); });
window.addEventListener("pagehide", release);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && wanted && !connecting) joinLive();
});

async function update() {
  try {
    const response = await fetch("/api/now", {cache: "no-store", signal: AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error("Station unavailable");
    const data = await response.json();
    const recovered = !stationLive || (stationId && stationId !== data.station_id);
    stationLive = data.status === "live";
    stationId = data.station_id;
    tune.disabled = !stationLive && !wanted;
    document.querySelector("#on-air").textContent = stationLive ? "● ON AIR" : "OFF AIR";
    document.querySelector("#demo").hidden = !data.demo;
    document.querySelector("#title").textContent = data.now?.title ?? (stationLive ? "Between tracks" : "Signal unavailable");
    document.querySelector("#artist").textContent = data.now?.artist ?? (stationLive ? "Diamond City Radio" : "The station needs to reconnect.");
    document.querySelector("#kind").textContent = data.now?.media_type?.toUpperCase() ?? "STANDBY";
    if (!stationLive) {
      release();
      status.textContent = "Station offline. Waiting for the broadcast to return.";
    } else if (recovered && wanted) joinLive();
    else if (recovered && !wanted) status.textContent = "The station is on air. Tune in to join the broadcast.";
  } catch {
    stationLive = false;
    release();
    tune.disabled = !wanted;
    document.querySelector("#on-air").textContent = "OFFLINE";
    document.querySelector("#title").textContent = "Signal unavailable";
    document.querySelector("#artist").textContent = "Waiting for the station…";
    document.querySelector("#kind").textContent = "STANDBY";
    status.textContent = "Cannot reach the station. Retrying…";
  } finally { setTimeout(update, 1000); }
}
update();
