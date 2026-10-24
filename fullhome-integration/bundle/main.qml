/* @@@LICENSE
 *
 * Copyright (c) 2018 LG Electronics, Inc.
 *
 * Confidential computer software. Valid license from LG required for
 * possession, use or copying. Consistent with FAR 12.211 and 12.212,
 * Commercial Computer Software, Computer Software Documentation, and
 * Technical Data for Commercial Items are licensed to the U.S. Government
 * under vendor's standard commercial license.
 *
 * LICENSE@@@ */

import QtQuick 2.6
import "AdaptationLayer"
import "AppInitializer"
import "UserInterfaceLayer"
import "Configurations"

import "./Utilities/Utils.js" as Utils

FocusScope {

    id: rootWindow

    // WiiOS diagnostics only: no redirect, close, reboot or settings change.

    // A time-limited lease also disables redirects in QML left resident after rollback.
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

    property int wiiosTraceSequence: 0
    function wiiosTrace(eventName, fields) {
        try {
            if (wiiosTraceSequence >= 500) return;
            wiiosTraceSequence++;
            var c = typeof uiController !== "undefined" ? uiController : null;
            var p = c && c.homeLaunchParams ? c.homeLaunchParams.parameters : null;
            var record = {
                token: "diag-3e891511b377", event: eventName, sequence: wiiosTraceSequence,
                time: new Date().getTime(), fields: fields || {},
                tempMode: c ? c.tempMode : null,
                currentMode: c ? c.currentMode : null,
                state: c ? c.stateAboutToChange : null,
                isBootingHome: c ? c.isBootingHome : null,
                homeKey: c ? c.homeLaunchByHomeKey : null,
                activateType: p ? p.activateType : null,
                launchType: p ? p.launchType : null
            };
            var line = "WIIOS_DIAG " + JSON.stringify(record);
            console.warn(line);
            rootWindow.printLog(line);
        } catch (error) {
            console.warn("WIIOS_DIAG diag-3e891511b377 trace-error " + String(error));
        }
    }

    width: videoSize !== undefined ? videoSize.width : 1920
    height: videoSize !== undefined ? videoSize.height : 1080

    visible: true
    focus: true

    property int webOS_CHANNEL_UP: 18874401
    property int webOS_CHANNEL_DOWN : 18874402
    property var keyCount: []

    //Application Properties
    property SystemProperties systemProperties: SystemProperties {
        appId: rootWindow.appId
        isAppRunning: rootWindow.isAppRunning
        stringSheet: rootWindow.stringSheet
        isRTLLocale: adaptationLayer.items.localeService ? adaptationLayer.items.localeService.isRTLLocale : false

        onIsAppForegroundChanged: {
            //            if(isAppForeground)rootWindow.registerWindowId();
            if(!isAppForeground) {
                rootWindow.playVideo(false);
            } else {
                if (!rootWindow.isAppRunning) {
                    rootWindow.isAppRunning = true;
                }
            }
        }
    }

    property SystemDataStorage systemDataStorage: SystemDataStorage {}

    property StringSheet stringSheet: StringSheet {
        emptyString: adaptationLayer.items.localeService ? adaptationLayer.items.localeService.emptyString : ""
        isRTL: adaptationLayer.items.localeService ? adaptationLayer.items.localeService.isRTLLocale : false
    }

    property string appId: "" //Initially empty for CRIU
    property var launchParams
    property bool active: false
    property bool cursorVisible: false
    property var videoSize
    property bool isAppRunning: false
    property var windowId
    property bool isHD : false

    property var utils: Utils

    property var homeLaunchParam

    //signals
    signal printLog(var value)
    signal printLS(var value)
    signal showWindow()
    signal hideWindow()
    signal invokeExit()
    signal setDebugLevel(string debugLevel)
    signal appClosing()
    signal enableLog()
    signal activateWindow(variant activateParam)
    signal setWindowProperty(variant propertyName, variant value)

    //PIP
    signal registerWindowId()
    signal changeWindowPosition(variant x, variant y, variant width, variant height)
    signal setVideoMute(bool mute)

    //Image Cache
    signal createCache()
    signal clearCache()
    signal changeCacheDirectory(variant url)
    signal saveCache(variant result, variant folderName, variant fileName)

    //Send KeyEvent to LiveTV
    signal sendKeyEvent(int key);

    //Internal signals
    signal fivewayKeyEvent(var keyCode)

    //Aliases

    //Platform Adaptation Layer
    AdaptationLayer {

        id: adaptationLayer

        objectName: "adaptationLayer"

        appId: rootWindow.appId

        onReady: {
            printLog("[LIFECYCLE] AdaptationLayer Ready");
            printLog("[LIFECYCLE] startRegister");

            if(rootWindow.launchParams && rootWindow.launchParams.reason !== "preload") {
                systemProperties.homePromotionData.push({"type" : "homeLaunchStartTime","time" : new Date()});
                performanceLogStart("Fresh Launch");
            }
            lifeCycleController.startInitialization(rootWindow.launchParams);
        }
    }

    //Process Launch Parameter
    AppLifeCycleController {

        id: lifeCycleController

        objectName: "lifeCycleController"

        appId: rootWindow.appId
        serviceComponent: adaptationLayer.items.serviceComponent

        onStart: {
            rootWindow.wiiosTrace("lifecycle.start", {mode: mode});
            printLog("[LIFECYCLE] start new mode: " + mode)

            if(!appInitializer.readyToRun) {
                printLog("[LIFECYCLE] start initializing: " + mode)
                uiController.tempMode = mode;

                printLog("[LIFECYCLE] startInitialize");
                appInitializer.startInitialize();
            } else {
                if(systemProperties.isAppReadyToUse) {
                    var boot = (launchParam.activateType === "powerOn") ? true : false
                    uiController.executeLaunch(mode, launchParam.param, boot);
                } else {
                    printLog("[LIFECYCLE] not ready to change mode");
                }
            }
        }

        onRegisterAppResponse: {
            if (response.event === "relaunch") rootWindow.wiiosIntent = rootWindow.wiiosReadIntent(response);
            rootWindow.wiiosTrace("lifecycle.register", {
                event: response.event,
                activateType: response.parameters ? response.parameters.activateType : null,
                launchType: response.parameters ? response.parameters.launchType : null
            });
            printLog("[LIFECYCLE] registerAppService event: " + JSON.stringify(response));
            uiController.homeLaunchParams = response;
            switch(response.event) {
            case "registered":
                break;

            case "relaunch":
                printLog("[LIFECYCLE] registerAppService launchParams: " + JSON.stringify(launchParam));
                if(!uiController.transitionRunning) {
                    uiController.setWindowVisible(true);
                }
                break;

            case "close":
                uiController.dismissApp(false);
                break;

            case "pause":
                uiController.dismissApp(true);
                break;
            }
        }

        onLifeStatusChanged: {
            rootWindow.wiiosTrace("lifecycle.status", {status: status});
            printLog("[LIFECYCLE] onLifeCycleChanged status:  " + status);
            systemProperties.lifeCycleStatus = status;
            switch(status) {
            case "launching":
                performanceLogStart(status);
                uiController.setWindowVisible(true);
                break;
            case "relaunching":
                performanceLogStart(status);
                uiController.setWindowVisible(true);
                break;
            case "foreground":
                rootWindow.isAppRunning = true;
                break;
            case "background":
                if(rootWindow.isAppRunning)
                    uiController.hideWindow();
                break;
            case "pausing":
                break;
            case "closing":
                break;
            case "stop":
                break;
            }
        }

        onRegisterAppServiceLoaded: {
            printLog("[LIFECYCLE] RegisterAppServiceLoaded");
            registerApp();
        }

        onAppLifeCycleServiceLoaded: {
            printLog("[LIFECYCLE] AppLifeCycleServiceLoaded")
            startSubscribeLifeCycle();
        }
    }

    AppInitializer {

        id: appInitializer

        active: rootWindow.active
        appId: rootWindow.appId
        systemProperties: rootWindow.systemProperties
        //        uiController: rootWindow.uiController
        serviceComponent: adaptationLayer.items.serviceComponent

        onReady: {
            printLog("[INITIALIZE] AppInitializer ready")
            systemProperties.isAppReadyToUse = true;
        }

        onInterfaceReady: {
            printLog("[INITIALIZE] Interfaces ready")
        }

        onPrimaryServicesReady: {
            printLog("[INITIALIZE] Service checker ready")
        }

        onEnvironmentReady: {
            printLog("[INITIALIZE] EnvironmentSetter ready");
        }

        onStillRunning: {
            printLog("[LIFECYCLE] still initializing");
        }

        onErrorOccured: {
            printLog(msg);
        }
    }

    //UI Controller
    UIController {

        id: uiController

        anchors.fill: parent

        Connections {

            target: rootWindow

            onFivewayKeyEvent: {
                uiController.fivewayKeyEvent(keyCode);
            }
        }

        Connections {
            target: appInitializer.interfaces.application ? appInitializer.interfaces.application : null
            // enabled: appInitializer.interfaces.application !== undefined
            ignoreUnknownSignals: true

            onDelayedLaunch: {
                uiController.dismissApp(false);
                uiController.reservedLaunch = launchInfo;
            }
        }

        onHomeShownChanged: {
            if(homeShown) {
                performanceLogEnd(uiController.state);
            }

        }
    }

    property bool doPlayVideo: uiController.homeShown && systemProperties.isAppForeground && uiController.mainTransitionFinished

    onDoPlayVideoChanged: {
        if(doPlayVideo) {
//            if(rootWindow.windowId === "")
//                rootWindow.registerWindowId();
            rootWindow.playVideo(true);
        }
    }

    //App Starting Point after CRIU dump/restore (App entry point)
    function appLaunched(launchParams, bRestored, isDevice) {

        printLog("[LIFECYCLE] Start Home" + " bRestored: " + bRestored + " isDevice: " + isDevice);
        rootWindow.launchParams = JSON.parse(launchParams);
        rootWindow.wiiosIntent = rootWindow.wiiosReadIntent(rootWindow.launchParams);
        rootWindow.wiiosTrace("main.appLaunched", {
            restored: bRestored, device: isDevice, reason: rootWindow.launchParams.reason,
            activateType: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.activateType : null,
            launchType: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.launchType : null,
            snapshot: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.snapshot : null
        });
        uiController.homeLaunchParams = rootWindow.launchParams;
        adaptationLayer.startSetting(isDevice)
    }

    //Slots for signals from the main process
    function windowIsVisible(isVisible) {
        rootWindow.isAppRunning = isVisible;
    }

    function focusIn(isFocused) {
        rootWindow.active = isFocused;
    }

    function remoteCursorOn(isOn) {
        rootWindow.cursorVisible = isOn;
    }

    function cacheDirectoryChanged(url) {
        rootWindow.changeCacheDirectory(url);
    }

    function keyPressEvent(keyCode) {

        switch (keyCode) {
        case Qt.Key_Left:
        case Qt.Key_Up:
        case Qt.Key_Right:
        case Qt.Key_Down:
        case Qt.Key_Return:
            rootWindow.fivewayKeyEvent(keyCode);
            keyCount = []
            break;
        case webOS_CHANNEL_UP:
        case webOS_CHANNEL_DOWN:
        case Qt.Key_0:
        case Qt.Key_1:
        case Qt.Key_2:
        case Qt.Key_3:
        case Qt.Key_4:
        case Qt.Key_5:
        case Qt.Key_6:
        case Qt.Key_7:
        case Qt.Key_8:
        case Qt.Key_9:
            if (uiController.isHalfMode) {
                rootWindow.sendKeyEvent(keyCode);
                uiController.dismissApp(false);
            }
            if(keyCount.length === 6){
                if(systemProperties.keyCounter === true){
                    systemProperties.keyCounter = false;
                    keyCount =[];
                }
                else{
                    systemProperties.keyCounter = true
                    keyCount = []
                }
            }
            else {
                if (keyCode === Qt.Key_7){
                    keyCount.push(keyCode)
                }
                else {
                    keyCount = []
                }
            }
            break;
        default:
            keyCount =[];
            break;
        }
    }

    function playVideo(on) {
        if (!systemProperties.isAppForeground && on) {
            printLog("[LIFECYCLE] Block playVideo true(not foreground status)")
            return;
        }

        printLog("[LIFECYCLE] playVideo on: " + on)
        rootWindow.setWindowProperty("playVideo", (on ? "true" : "false"));
    }

    function windowIdAssigned(windowId, type) {
        //        interfaces.pip.setWindowId(windowId, type);
        printLog("windowId " + windowId)
        rootWindow.windowId = windowId;
    }

    //Performance Log
    function performanceLogStart(status) {
        if(adaptationLayer.items.logger)
            adaptationLayer.items.logger.performanceLog.logInfoWithClock("HOME_LAUNCH_START", {"PerfGroup": "com.webos.app.fullhome", "PerfType": "AppLaunch"}, status + " Home App");
    }

    //Performance Log
    function performanceLogEnd(status) {
        if(adaptationLayer.items.logger)
            adaptationLayer.items.logger.performanceLog.logInfoWithClock("HOME_LAUNCH_END", {"PerfGroup": "com.webos.app.fullhome", "PerfType": "AppLaunch"}, status + " Home execution is complete");
    }

    Connections {
        target: uiController

        onShowWindow: {
            printLog("[LIFECYCLE] showWindow");
            rootWindow.showWindow();
        }

        onHideWindow: {
            printLog("[LIFECYCLE] hideWindow");
            rootWindow.hideWindow();
        }

        onKillWindow: {
            printLog("[LIFECYCLE] killWindow");
            rootWindow.invokeExit();
        }

        onStateChanged: {
            if (uiController.isHiddenMode) {
                if(appInitializer.interfaces.audioguide) {
                    appInitializer.interfaces.audioguide.stopGuide();
                    appInitializer.interfaces.audioguide.blockByReadScene = false;
                }
            }
        }
    }

    Connections {
        target: rootWindow

        onFivewayKeyEvent: {
            if(appInitializer.interfaces.audioguide) {
                appInitializer.interfaces.audioguide.pressedFiveWayKey();
            }
        }

        onPrintLog: {
//            console.log(value)
        }

        onActiveChanged: {
            if(active)
                printLog("[LIFECYCLE] App window active")
            else
                printLog("[LIFECYCLE] App window inactive")
        }
    }

    Component.onCompleted: {
        rootWindow.wiiosTrace("main.completed", {});
        printLog("[LIFECYCLE] Component.onCompleted")
        rootWindow.setWindowProperty("delayCloseWindowTimeout", 2000);
    }

    Component.onDestruction: {
        printLog("[LIFECYCLE] Component.onDestruction")
        rootWindow.appClosing();
    }
}
