"""
Envoi d'alertes (email + Discord) quand une aubaine est detectee.
"""

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import Request, urlopen

from config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, ALERT_RECIPIENTS, DISCORD_WEBHOOK_URL


def send_deal_alert(deals):
    """Envoie un email recapitulatif des aubaines detectees."""
    if not deals:
        return

    has_error_fare = any(d.get("error_fare") for d in deals)
    if has_error_fare:
        subject = f"ERREUR DE PRIX POSSIBLE ! {len(deals)} aubaine(s) detectee(s)"
    else:
        subject = f"Alerte Vol Pas Cher ! {len(deals)} aubaine(s) detectee(s)"

    # Corps du message en HTML — design sombre moderne
    html = """
    <html>
    <body style="margin:0;padding:0;background:#121318;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="max-width:720px;margin:0 auto;background:#121318;">

    <!-- HEADER -->
    <div style="background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);padding:36px 32px 28px;border-radius:0 0 16px 16px;">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td><span style="font-size:28px;font-weight:800;color:#fff;letter-spacing:-0.5px;">&#9992; MesVols</span></td>
        <td style="text-align:right;"><span style="background:rgba(13,148,136,0.2);color:#0d9488;padding:5px 14px;border-radius:100px;font-size:12px;font-weight:600;">&#9679; Live</span></td>
      </tr></table>
      <h1 style="margin:18px 0 6px;font-size:22px;color:#fff;font-weight:700;">""" + (
        f'{len(deals)} aubaine{"s" if len(deals) > 1 else ""} detect&eacute;e{"s" if len(deals) > 1 else ""} !'
    ) + """</h1>
      <p style="margin:0;color:rgba(255,255,255,0.5);font-size:13px;">""" + (
        "&#128680; Erreur de prix possible — r&eacute;servez vite !" if has_error_fare
        else "Des prix int&eacute;ressants ont &eacute;t&eacute; trouv&eacute;s aujourd'hui."
    ) + """</p>
    </div>

    <!-- TABLE -->
    <div style="padding:24px 16px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:0 8px;">
      <tr>
        <th style="padding:8px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Route</th>
        <th style="padding:8px 12px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Prix</th>
        <th style="padding:8px 12px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Moyenne</th>
        <th style="padding:8px 12px;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Rabais</th>
        <th style="padding:8px 12px;text-align:center;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Escales</th>
        <th style="padding:8px 12px;text-align:center;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Score</th>
        <th style="padding:8px 12px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;">Compagnie</th>
        <th style="padding:8px 12px;text-align:center;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7085;"></th>
      </tr>
    """

    for deal in deals:
        stops = deal.get("stops", "")
        is_direct = deal.get("num_stops", 1) == 0
        is_error_fare = deal.get("error_fare", False)
        near_minimum = deal.get("near_minimum", False)
        hist_min = deal.get("hist_min", "")
        score = deal.get("score", 0)
        score_stars = "&#9733;" * score + "&#9734;" * (5 - score) if score else ""

        # Construire l'URL de reservation (Skyscanner)
        origin = deal.get("origin", "YUL")
        dest = deal.get("destination", "")
        depart = deal.get("depart", "")
        retour = deal.get("retour", "")
        sky_dep = depart.replace("-", "")[2:]
        sky_ret = retour.replace("-", "")[2:]
        booking_url = (
            f"https://www.skyscanner.ca/transport/flights/"
            f"{origin.lower()}/{dest.lower()}/{sky_dep}/{sky_ret}/"
            f"?adultsv2=1&currency=CAD&locale=fr-CA&market=CA"
        )

        # Badge escales
        if is_direct:
            direct_badge = (
                '<span style="background:rgba(13,148,136,0.15);color:#0d9488;'
                'padding:3px 10px;border-radius:100px;font-size:11px;'
                'font-weight:700;">Direct</span>'
            )
        else:
            direct_badge = (
                f'<span style="background:rgba(107,112,133,0.15);color:#a0a5b8;'
                f'padding:3px 10px;border-radius:100px;font-size:11px;">{stops}</span>'
            )

        # Couleur de la bordure gauche selon le type
        if is_error_fare:
            accent = "#e11d48"
            row_bg = "#1e1520"
        elif is_direct:
            accent = "#0d9488"
            row_bg = "#141e1d"
        elif near_minimum:
            accent = "#d97706"
            row_bg = "#1c1a14"
        else:
            accent = "#e85d24"
            row_bg = "#1a1a22"

        # Badge special sous la route
        sub_badge = ""
        if is_error_fare:
            sub_badge = (
                '<br><span style="background:#e11d48;color:#fff;padding:2px 8px;'
                'border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.5px;'
                'text-transform:uppercase;">Erreur de prix</span>'
            )
        elif near_minimum:
            sub_badge = (
                f'<br><span style="color:#d97706;font-size:10px;">'
                f'&#9733; Proche du min ({hist_min} $)</span>'
            )

        # Dates du vol
        date_info = ""
        if depart and retour:
            date_info = (
                f'<br><span style="color:#6b7085;font-size:10px;">'
                f'{depart} &rarr; {retour}</span>'
            )

        html += f"""
      <tr>
        <td style="padding:14px 12px;background:{row_bg};border-left:3px solid {accent};border-radius:8px 0 0 8px;color:#fff;font-size:13px;font-weight:600;">
          {deal['route']}{date_info}{sub_badge}
        </td>
        <td style="padding:14px 12px;background:{row_bg};text-align:right;color:#0d9488;font-weight:800;font-size:16px;">
          {deal['price']}&nbsp;$
        </td>
        <td style="padding:14px 12px;background:{row_bg};text-align:right;color:#6b7085;font-size:13px;text-decoration:line-through;">
          {deal['average']}&nbsp;$
        </td>
        <td style="padding:14px 12px;background:{row_bg};text-align:right;">
          <span style="background:rgba(5,150,105,0.15);color:#059669;padding:3px 10px;border-radius:100px;font-size:12px;font-weight:700;">
            &darr; {deal['discount_pct']}%
          </span>
        </td>
        <td style="padding:14px 12px;background:{row_bg};text-align:center;">{direct_badge}</td>
        <td style="padding:14px 8px;background:{row_bg};text-align:center;color:#d97706;font-size:13px;white-space:nowrap;">{score_stars}</td>
        <td style="padding:14px 12px;background:{row_bg};color:#a0a5b8;font-size:12px;">{deal['airline']}</td>
        <td style="padding:14px 12px;background:{row_bg};text-align:center;border-radius:0 8px 8px 0;">
          <a href="{booking_url}" target="_blank"
             style="display:inline-block;background:#e85d24;color:#fff;padding:8px 18px;
                    border-radius:8px;font-size:12px;font-weight:700;text-decoration:none;
                    letter-spacing:0.3px;">R&eacute;server &rarr;</a>
        </td>
      </tr>
        """

    html += """
    </table>
    </div>

    <!-- FOOTER -->
    <div style="padding:20px 32px 32px;text-align:center;">
      <p style="color:#6b7085;font-size:11px;line-height:1.6;margin:0;">
        P&eacute;riodes scrut&eacute;es : J+30, J+60 et J+90 &middot; Vols aller-retour<br>
        &#9733;&#9733;&#9733;&#9733;&#9733; = direct + prix bas &middot; &#9733;&#9733;&#9734;&#9734;&#9734; = 2+ escales<br>
        <span style="color:#e11d48;">ERREUR DE PRIX</span> = rabais &gt; 60 % — r&eacute;servez imm&eacute;diatement<br>
        <span style="color:#3a3a4a;">Envoy&eacute; automatiquement par MesVols</span>
      </p>
    </div>

    </div>
    </body>
    </html>
    """

    # Version texte
    text_lines = ["Aubaines detectees !\n"]
    for deal in deals:
        stops = deal.get("stops", "")
        score = deal.get("score", 0)
        error_tag = " [ERREUR DE PRIX POSSIBLE]" if deal.get("error_fare") else ""
        min_tag = f" [proche min: {deal.get('hist_min')} $]" if deal.get("near_minimum") else ""
        text_lines.append(
            f"  {deal['route']}: {deal['price']} $ CAD "
            f"(moyenne {deal['average']} $, -{deal['discount_pct']}%) "
            f"- {deal['airline']} [{stops}] Score: {score}/5{error_tag}{min_tag}"
        )
    text = "\n".join(text_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(ALERT_RECIPIENTS)
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, ALERT_RECIPIENTS, msg.as_string())
        print(f"\nEmail d'alerte envoye a {', '.join(ALERT_RECIPIENTS)}")
    except Exception as e:
        print(f"\nErreur envoi email: {e}")
        print("Verifie ton adresse Gmail et ton mot de passe d'application dans config.py")

    # Notification Discord
    send_discord_alert(deals)


def send_discord_alert(deals):
    """Envoie un message Discord avec embeds pour chaque aubaine."""
    if not deals or not DISCORD_WEBHOOK_URL:
        return

    has_error_fare = any(d.get("error_fare") for d in deals)

    embeds = []
    for deal in deals:
        is_error_fare = deal.get("error_fare", False)
        is_direct = deal.get("num_stops", 1) == 0
        near_minimum = deal.get("near_minimum", False)
        score = deal.get("score", 0)
        stars = "\u2605" * score + "\u2606" * (5 - score) if score else ""

        # Couleur de l'embed
        if is_error_fare:
            color = 0xe11d48
        elif is_direct:
            color = 0x0d9488
        elif near_minimum:
            color = 0xd97706
        else:
            color = 0xe85d24

        # URL de reservation Skyscanner
        origin = deal.get("origin", "YUL")
        dest = deal.get("destination", "")
        depart = deal.get("depart", "")
        retour = deal.get("retour", "")
        sky_dep = depart.replace("-", "")[2:]
        sky_ret = retour.replace("-", "")[2:]
        booking_url = (
            f"https://www.skyscanner.ca/transport/flights/"
            f"{origin.lower()}/{dest.lower()}/{sky_dep}/{sky_ret}/"
            f"?adultsv2=1&currency=CAD&locale=fr-CA&market=CA"
        )

        # Badges texte
        tags = []
        if is_error_fare:
            tags.append("\U0001f6a8 **ERREUR DE PRIX**")
        if is_direct:
            tags.append("\u2708\ufe0f Direct")
        if near_minimum:
            tags.append(f"\u2b50 Proche du min ({deal.get('hist_min', '?')} $)")

        description = (
            f"**{deal['price']} $ CAD** ~~{deal['average']} $~~ \u2014 **-{deal['discount_pct']}%**\n"
            f"\U0001f6eb {depart}  \u2192  \U0001f6ec {retour}\n"
            f"{deal.get('stops', '')} \u00b7 {deal.get('airline', '?')} \u00b7 {stars}\n"
        )
        if tags:
            description += " \u00b7 ".join(tags) + "\n"
        description += f"\n[\U0001f4b3 Reserver sur Skyscanner]({booking_url})"

        embeds.append({
            "title": deal["route"],
            "description": description,
            "color": color,
        })

    # Discord limite a 10 embeds par message
    title = (
        "\U0001f6a8 ERREUR DE PRIX POSSIBLE !" if has_error_fare
        else f"\u2708\ufe0f {len(deals)} aubaine{'s' if len(deals) > 1 else ''} detectee{'s' if len(deals) > 1 else ''} !"
    )

    payload = json.dumps({
        "content": f"## {title}",
        "embeds": embeds[:10],
    }).encode("utf-8")

    req = Request(DISCORD_WEBHOOK_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        urlopen(req)
        print("Notification Discord envoyee !")
    except Exception as e:
        print(f"Erreur envoi Discord: {e}")
