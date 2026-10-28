HOME_IDS = ('com.webos.app.fullhome', 'com.webos.app.home')


def classify_home(app_id, manifest, hashes):
    kind = manifest.get('type')
    if app_id == 'com.webos.app.fullhome' and len(hashes) == 2:
        return 'qml', 'verified-qml-paths'
    if kind in ('web', 'flutter', 'native'):
        return kind, 'manifest-type'
    if kind in (None, '', 'unknown'):
        main = manifest.get('main')
        if isinstance(main, str) and main.startswith('/usr/bin/'):
            return 'native', 'native-executable-path'
    return 'unknown', 'unrecognized-manifest'


def sam_registration(app_id, response):
    if not isinstance(response, dict) or response.get('returnValue') is not True:
        return {'registered': False, 'homeRole': False, 'type': None}
    info = response.get('appInfo')
    if not isinstance(info, dict) or info.get('id') != app_id:
        return {'registered': False, 'homeRole': False, 'type': None}
    kind = info.get('type')
    categories = info.get('appCategory')
    return {'registered': True, 'homeRole': isinstance(categories, list) and 'home' in categories,
            'type': kind if kind in ('web', 'flutter', 'native') else None}


def choose_home(candidates, running):
    if not candidates:
        return None, 'no-home-manifest'
    registered = [item for item in candidates if item['sam']['registered']]
    home_roles = [item for item in registered if item['sam']['homeRole']]
    if len(home_roles) == 1:
        return home_roles[0], 'unique-sam-home-role'
    if len(home_roles) > 1:
        return None, 'ambiguous-sam-home-role'
    if len(registered) == 1:
        return registered[0], 'unique-sam-registration'
    active = [item for item in registered if item['appId'] in running]
    if len(active) == 1:
        return active[0], 'sam-registered-running-home'
    return None, 'ambiguous-home-registration' if registered else 'home-unregistered'
