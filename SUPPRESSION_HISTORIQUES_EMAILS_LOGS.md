# Suppression des historiques d’e-mails et du journal d’audit

- Les tables `EnvoiEmail`, `DestinataireEnvoiEmail` et `JournalAudit` sont supprimées par la migration `0056_supprimer_historiques_emails_et_journal`.
- Aucun objet, contenu, destinataire, pièce jointe, erreur ou résultat d’envoi n’est conservé en base.
- L’historique des e-mails a été retiré de la fiche salarié et de la page E-mails.
- L’onglet Historique et le journal d’audit ont été retirés de l’administration.
- Le middleware d’audit et la configuration de journalisation spécifique aux e-mails ont été supprimés.
- L’envoi d’e-mails, les modèles réutilisables et les contacts externes restent disponibles.

Après déploiement :

```bash
python manage.py migrate
```
