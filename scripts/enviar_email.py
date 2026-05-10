"""Envía tu plan del día por correo (vía SMTP de Gmail).

Setup:
  Ver integraciones/README_email.md (necesitas contraseña de aplicación)

Uso:
  python scripts/enviar_email.py
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from comun import cargar, cargar_registro_dia


def construir_html(plan: dict, fecha: str) -> str:
    if not plan:
        return f"<p>No hay plan generado para {fecha}.</p>"

    bloques_html = ""
    for b in plan.get("bloques", []):
        icono = {"tarea": "📌", "habito": "🎯", "descanso": "☕"}.get(b.get("tipo", ""), "•")
        bloques_html += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #eee;font-family:monospace;color:#666;width:70px;">{b.get('hora','')}</td>
          <td style="padding:10px;border-bottom:1px solid #eee;">
            <strong>{icono} {b.get('titulo','')}</strong>
            <div style="color:#888;font-size:13px;margin-top:4px;">
              {b.get('empresa','')} · {b.get('duracion_min',0)} min
            </div>
            {f"<div style='color:#a78bfa;font-size:12px;margin-top:3px;'>💡 {b['razon']}</div>" if b.get('razon') else ""}
          </td>
        </tr>"""

    advertencia = f"<div style='background:#fef3c7;padding:12px;border-radius:8px;margin:16px 0;'>⚠️ {plan['advertencia']}</div>" if plan.get("advertencia") else ""

    return f"""
    <div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;color:#222;">
      <h1 style="color:#FF6B35;">☀️ Plan del día — {fecha}</h1>
      <p style="font-size:16px;">{plan.get('saludo','')}</p>
      {advertencia}
      <table style="width:100%;border-collapse:collapse;background:#fafafa;border-radius:10px;overflow:hidden;">
        {bloques_html}
      </table>
      <p style="color:#888;margin-top:20px;">🏁 {plan.get('frase_cierre','')}</p>
    </div>
    """


def main() -> None:
    config = cargar("config.json")
    cfg = config["email"]
    if not cfg["remitente"] or not cfg["destinatario"]:
        print("⚠️  Configura primero remitente y destinatario en datos/config.json")
        raise SystemExit(1)

    password = os.getenv("EMAIL_PASSWORD")
    if not password:
        print("⚠️  Falta variable EMAIL_PASSWORD (contraseña de aplicación de Gmail)")
        print("    Ver integraciones/README_email.md")
        raise SystemExit(1)

    hoy = date.today().isoformat()
    registro = cargar_registro_dia(hoy)
    plan = registro.get("plan_generado")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"☀️ Tu plan del {hoy}"
    msg["From"] = cfg["remitente"]
    msg["To"] = cfg["destinatario"]
    msg.attach(MIMEText(construir_html(plan, hoy), "html"))

    with smtplib.SMTP(cfg["smtp_servidor"], cfg["smtp_puerto"]) as s:
        s.starttls()
        s.login(cfg["remitente"], password)
        s.send_message(msg)

    print(f"✅ Plan enviado a {cfg['destinatario']}")


if __name__ == "__main__":
    main()
