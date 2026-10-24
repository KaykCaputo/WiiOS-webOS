from prepare import replace_once

def add_redirect(patches, deadline_ms):
    keys = list(patches)
    main, ctrl = (patches[key].decode() for key in keys)
    intent = '''
    property string wiiosIntent: ""
    function wiiosReadIntent(envelope) {
        var p = envelope && envelope.parameters ? envelope.parameters : {};
        if (p.wiiosNativeHome === true || p.snapshot === true || envelope.reason === "preload") return "";
        if (p.activateType === "powerOn") return "powerOn";
        if (p.activateType && p.activateType !== "home" && p.activateType !== "myapps") return "";
        if (p.launchType === "homeKey") return "homeKey";
        if (p.activateType === "home" || p.activateType === "myapps") return "home";
        return "";
    }
'''
    main = replace_once(main, '    property int wiiosTraceSequence: 0', intent + '\n    property int wiiosTraceSequence: 0')
    main = replace_once(main, '        rootWindow.launchParams = JSON.parse(launchParams);', '''        rootWindow.launchParams = JSON.parse(launchParams);
        rootWindow.wiiosIntent = rootWindow.wiiosReadIntent(rootWindow.launchParams);''')
    main = replace_once(main, '        onRegisterAppResponse: {', '''        onRegisterAppResponse: {
            if (response.event === "relaunch") rootWindow.wiiosIntent = rootWindow.wiiosReadIntent(response);''')
    redirect = '''
    property bool wiiosRedirectPending: false
    property bool wiiosFallback: false
    property int wiiosRequestSequence: 0
    property var wiiosFallbackArgs: []
    Timer {
        id: wiiosLaunchTimeout
        interval: 4000
        repeat: false
        onTriggered: root.wiiosResumeNative("timeout")
    }
    function wiiosResumeNative(reason) {
        if (!root.wiiosRedirectPending) return;
        root.wiiosRedirectPending = false;
        wiiosLaunchTimeout.stop();
        rootWindow.wiiosTrace("redirect.fallback", {reason: reason});
        root.wiiosFallback = true;
        try {
            root.executeLaunch(root.wiiosFallbackArgs[0], root.wiiosFallbackArgs[1], root.wiiosFallbackArgs[2]);
        } finally { root.wiiosFallback = false; }
    }
    function wiiosTryRedirect(mode, extraParam, boot) {
        if (root.wiiosFallback || new Date().getTime() >= @DEADLINE@) return false;
        if (mode !== "main" && mode !== "home" && mode !== "myapps" && mode !== "powerOn") return false;
        if (!rootWindow.wiiosIntent) return false;
        if (!interfaces.application || typeof interfaces.application.simpleLaunch !== "function") return false;
        if (root.wiiosRedirectPending) return true;
        var intent = rootWindow.wiiosIntent;
        rootWindow.wiiosIntent = "";
        root.wiiosRedirectPending = true;
        root.wiiosFallbackArgs = [mode, extraParam, boot];
        var request = ++root.wiiosRequestSequence;
        rootWindow.wiiosTrace("redirect.request", {intent: intent, mode: mode});
        wiiosLaunchTimeout.restart();
        try {
            interfaces.application.simpleLaunch("com.wiios.launcher", {}, function (response) {
                if (request !== root.wiiosRequestSequence || !root.wiiosRedirectPending) return;
                if (!response || response.returnValue !== true) {
                    root.wiiosResumeNative("launch-rejected");
                    return;
                }
                root.wiiosRedirectPending = false;
                wiiosLaunchTimeout.stop();
                rootWindow.wiiosTrace("redirect.accepted", {appId: "com.wiios.launcher"});
                root.dismissApp(false);
            });
        } catch (error) {
            wiiosLaunchTimeout.stop();
            root.wiiosRedirectPending = false;
            rootWindow.wiiosTrace("redirect.error", {message: String(error)});
            return false;
        }
        return true;
    }
'''.replace('@DEADLINE@', str(deadline_ms))
    ctrl = replace_once(ctrl, '    id: root\n', '    id: root\n' + redirect)
    ctrl = replace_once(ctrl, '    function executeLaunch(mode, extraParam, isBootingHome) {', '''    function executeLaunch(mode, extraParam, isBootingHome) {
        if (root.wiiosTryRedirect(mode, extraParam, isBootingHome)) return;''')
    return {keys[0]: main.encode(), keys[1]: ctrl.encode()}
