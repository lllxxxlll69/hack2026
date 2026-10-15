"""Generate local secrets once; never replace an existing .env."""
import argparse
import base64
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='dean')
    parser.add_argument('--email', default='dean@example.local')
    args = parser.parse_args()
    target = ROOT / '.env'
    if target.exists():
        print('.env already exists; secrets preserved.')
        return
    db_password = secrets.token_hex(24)
    password = secrets.token_urlsafe(18)
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    text = text.replace('replace-with-a-long-random-password', db_password)
    text = text.replace('replace-with-at-least-12-characters', password)
    text = text.replace('generate-with-scripts-setup', base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    text = text.replace('BOOTSTRAP_USERNAME=dean', 'BOOTSTRAP_USERNAME=' + args.username)
    text = text.replace('BOOTSTRAP_EMAIL=dean@example.local', 'BOOTSTRAP_EMAIL=' + args.email)
    with target.open('x', encoding='utf-8') as stream:
        stream.write(text)
    print('Created .env. Initial dean credentials are in BOOTSTRAP_USERNAME / BOOTSTRAP_PASSWORD.')
    print('Keep ENCRYPTION_KEY unchanged: it decrypts the database and uploaded files.')


if __name__ == '__main__':
    main()
