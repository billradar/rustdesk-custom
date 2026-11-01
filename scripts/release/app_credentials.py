"""Validate public release App configuration without reading or printing a key."""
import os


def require_configuration(client_id, key_present):
    if not client_id.strip() or key_present != 'true':
        raise ValueError('Release App configuration missing: set repository Variable '
                         'RELEASE_APP_CLIENT_ID and Secret RELEASE_APP_PRIVATE_KEY; '
                         'install the App on this repository with Contents/Workflows write '
                         'and Actions read. See docs/release-app.md. Never put the private key in logs.')


if __name__ == '__main__':
    require_configuration(os.environ.get('RELEASE_APP_CLIENT_ID', ''),
                          os.environ.get('RELEASE_APP_KEY_PRESENT', 'false'))
    print('Release App configuration present (key not read); installation permissions are checked when minting the release token.')
