# ANA Business Award Watch (NYC → Tokyo Haneda)

Checks every 4 hours for ANA business-class partner award seats (the ones Virgin Atlantic can book), shows them on a web page, and sends a push notification to your phone when new dates appear.

## Setup (about 20 minutes, no coding)

1. **seats.aero Pro.** Subscribe at seats.aero, then go to Settings → API and copy your API key.
2. **Phone alerts.** Install the free **ntfy** app (iOS/Android). Tap +, then subscribe to a topic with a hard-to-guess name like `natalie-ana-7f3k2`. Your dad can subscribe to the same topic on his phone.
3. **GitHub.** Create a free account and a new **private** repository. Upload all of these files, keeping the folder structure (including the hidden `.github` folder).
4. **Secrets.** In the repo, go to Settings → Secrets and variables → Actions → *New repository secret* and add:
   - `SEATS_AERO_API_KEY` = your key
   - `NTFY_TOPIC` = your topic name
5. **Optional settings** (same page, *Variables* tab):
   - `DESTINATIONS` = `HND,NRT` to also watch Narita
   - `MIN_SEATS` = `2` if two people need to fly together
   - `NONSTOP_ONLY` = `false` to include connections
6. **First run.** Go to the Actions tab → "Check ANA award space" → *Run workflow*. After that it runs on its own.
7. **Dashboard.** Go to Settings → Pages, choose *Deploy from branch*, then pick `main` and the `/docs` folder. Bookmark the URL it gives you. (A private repo needs GitHub Pro for Pages. Otherwise make the repo public. The only thing it exposes is the flight data. Your key stays in Secrets.)

## Notes
- Alerts fire only for dates that weren't there on the previous check, so you won't get spammed.
- seats.aero data is cached and can be hours old. Always confirm on united.com or ana.co.jp before calling Virgin.
- Never transfer Amex points until the Virgin agent confirms they can see the seat. Transfers can't be reversed.
