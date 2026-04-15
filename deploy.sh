#!/usr/bin/env bash
# deploy.sh — Déploie le module inies_connector sur le serveur Odoo
# Usage : ./deploy.sh

set -e

SERVER="82.165.222.171"
ADDON_PATH="/opt/odoo19/addons/inies_connector"
ODOO_URL="https://ibatix.neosoft.cloud"
ODOO_DB="ibatix"
ODOO_USER="jj.beol@gmail.com"
ODOO_PASS="Odeli@@;-)2009"

echo "=== 1/3  Push vers GitHub ==="
git push

echo "=== 2/3  Pull sur le serveur ==="
ssh root@${SERVER} "
  cd ${ADDON_PATH} && git pull &&
  docker exec -u root odoo19_app bash -c '
    find /opt/odoo/addons/inies_connector -name \"*.pyc\" -delete 2>/dev/null
    rm -rf /opt/odoo/addons/inies_connector/wizard/__pycache__
    chown -R odoo:odoo /opt/odoo/addons/inies_connector
  ' &&
  docker restart odoo19_app
"

echo "Attente redémarrage Odoo (35s)..."
sleep 35

echo "=== 3/3  Upgrade du module ==="
python3 - <<PYEOF
import xmlrpc.client, ssl, sys

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

url  = "${ODOO_URL}"
db   = "${ODOO_DB}"
user = "${ODOO_USER}"
pwd  = "${ODOO_PASS}"

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", context=ctx)
uid = common.authenticate(db, user, pwd, {})
if not uid:
    print("Erreur : authentification Odoo échouée")
    sys.exit(1)

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", context=ctx)
mod_ids = models.execute_kw(db, uid, pwd,
    'ir.module.module', 'search', [[['name', '=', 'inies_connector']]])
models.execute_kw(db, uid, pwd,
    'ir.module.module', 'button_immediate_upgrade', [mod_ids])
print("Module mis à jour avec succès.")
PYEOF

echo ""
echo "Déploiement terminé."
