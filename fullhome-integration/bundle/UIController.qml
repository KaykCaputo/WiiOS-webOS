/* @@@LICENSE
 *
 * Copyright (c) 2020 LG Electronics, Inc.
 *
 * Confidential computer software. Valid license from LG required for
 * possession, use or copying. Consistent with FAR 12.211 and 12.212,
 * Commercial Computer Software, Computer Software Documentation, and
 * Technical Data for Commercial Items are licensed to the U.S. Government
 * under vendor's standard commercial license.
 *
 * LICENSE@@@ */

import QtQuick 2.6
import "Components"
import "Containers"
import "../Debug"

FocusScope {

    id: root

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
        if (root.wiiosFallback || false /* WiiOS permanent mode; no QML lease */) return false;
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

    Component.onCompleted: rootWindow.wiiosTrace("controller.completed", {})

    objectName: "uiController"

    property bool windowActive: rootWindow.active || rootWindow.focus
    property bool audioGuidanceOn: systemProperties.audioGuidanceOn

    property var fontManager: adaptationLayer.items.fontManager
    property var interfaces: appInitializer.interfaces
    property var webOS: adaptationLayer.items.webOSGlobalKeys
    property var styleLoader: adaptationLayer.items.styleLoader.styleLoader

    property var styleSheet: mainView.styleSheet

    property alias mainView: viewLoader.item
    property alias userLogger: userLogger

    property bool transitionRunning: false
    property bool mainTransitionFinished: false
    property bool textAnimationRunning: false
    property bool mainRibbonScrolling: false
    property bool introRan: false

    property string currentMode: "main"
    property string tempMode: "hidden"

    property bool isAppStarted: rootWindow.isAppRunning
    property bool homeShown: rootWindow.isAppRunning && introRan
    property bool homeLaunchByHomeKey: homeLaunchParams && homeLaunchParams.parameters && homeLaunchParams.parameters.launchType === "homeKey"
    property bool showHeroBanner: systemProperties.showPromotionTile && isHomeADLaunched
    property bool refreshShelves: systemProperties.refreshCPList && homeShown
    property bool delayAddRemove: root.homeShown
    property bool isHomeADLaunched : false
    property bool mainRibbonReady: false

    property bool fullUpdating: false

    property bool editTilePressed: false

    property bool voiceEdit: false

    property bool isAutoLaunch: false
    property string stateAboutToChange: "hidden"
    property bool isHiddenMode: root.stateAboutToChange === "hidden"
    property bool isMainMode: root.stateAboutToChange === "main"
    property bool isHalfMode: root.stateAboutToChange === "half"
    property bool isSubMode: root.stateAboutToChange === "sub"
    property bool isEditMode: root.stateAboutToChange === "editMenu"
    property string editModeState: "none"

    property bool isFullHome: false

    property var selectables: []
    property var currentShelfSelectable: []
    property string scrollShelfId: ""
    property var removable: null
    property int pushCount: 0
    property int totalPushedCount: state === "editMenu" ? editModeState === "appEditPage" ? (mainView.settingPopup.visible ? 3 : 2) : (mainView.settingPopup.visible ? 2 : 1) : (mainView ? shelfReadyCount: 0)
    property int shelfReadyCount: 0
    property var shelfListReadyObj: ({})
    property bool startNavigation: false
    property bool needToHomeTitleSpeak: true
    property bool activeShelfAnimation: false
    property bool isBootingHome: false

    property var homeLaunchParams: ({})
    property bool checkInitPopupHomeShown: homeShown && systemProperties.isSettingsReady

    signal closing()
    signal readyToClose()
    signal appLaunched()

    signal dismissTimerExpired()
    signal extendTimer()
    signal subRibbonScrollingStopped()
    signal shelfListScrollingStopped()

    signal showWindow()
    signal hideWindow()
    signal killWindow()

    signal fivewayKeyEvent(var keyCode)

    signal setVoiceControlContext()
    signal setVoiceControlContextForEdit()
    signal pushIntents(var shelfId, var intents, var isShelfCenterPointOnScreen)
    signal performVoiceControl(var action)
    signal performVoiceControlForEdit(var action)
    signal reportAction(var result, var feedbackString)
    signal settingPopupClosed()

    signal retryShelfData()

    signal setFocusAfterAdLaunchFail()

    onReportAction: {
        var feedback = {
            "voiceUi": {
                "systemUtterance": feedbackString
            }
        }
        interfaces.voice.reportActionResult(result, feedback);
    }

    onHomeLaunchByHomeKeyChanged: {
        rootWindow.wiiosTrace("controller.homeKeyChanged", {value: homeLaunchByHomeKey});
        printLog("[UiController] homeLaunchByHomeKey : " + homeLaunchByHomeKey);
        if (homeLaunchParams && homeLaunchParams.parameters) {
            printLog("[UiController] launchType : " + homeLaunchParams.parameters.launchType);
        }
    }

    onPushIntents: {
        printLog("================push intents : "+shelfId + " "+totalPushedCount + " "+isShelfCenterPointOnScreen);
        pushCount++;

        if(isShelfCenterPointOnScreen && intents !== undefined) {
            intents.map(function (item, index) {
                if(item.intent === "Select") {
                    if(item.isActiveFocused) {
                        currentShelfSelectable = item.items;
                    } else {
                        selectables = selectables.concat(item.items);
                    }
                } else if(item.intent === "Scroll") {
                    scrollShelfId = item.itemId;
                } else if(item.intent === "Delete") {
                    removable = item;
                }
            });
        }

        if(pushCount === totalPushedCount) {
            var select = {
                "intent": "Select",
                "supportOrdinal": false,
                "items": selectables
            };

            var focusedSelect = {
                "intent": "Select",
                "supportOrdinal": true,
                "items": currentShelfSelectable
            };

            var scroll = {
                "intent": "Scroll",
                "itemId": "mainView",
                "direction": "both"  // [vertical, horizontal, both]
            };

            var finalIntents = [];
            finalIntents.push(select);
            finalIntents.push(focusedSelect);
            finalIntents.push(scroll);

            if(removable !== null) {
                finalIntents.push(removable);
            }

            interfaces.voice.setContext(finalIntents);

            selectables.length = 0;
            currentShelfSelectable.length = 0;
            removable = null;
        }
    }

    anchors.fill: parent
    focus: true

    Rectangle {

        anchors.fill: parent
        color: "#000000"
        visible: root.isEditMode
    }

    Loader {

        id: viewLoader

        objectName: "viewLoader"

        anchors.fill: parent

        active: systemProperties.isAppReadyToUse

        source: systemProperties.isWEE ? "./Containers/MainView_WEE.qml" : "./Containers/MainView.qml"
        asynchronous: true

        onLoaded: {
            printLog("[mainView] viewLoader loaded!");
            root.executeLaunch(root.tempMode);
            item.initialize();
        }
    }

    onMainRibbonReadyChanged: {
        if(mainRibbonReady) {
            //            root.executeLaunch(root.tempMode);
            uiController.extendTimer();
        }
    }

    Connections {
        target: systemProperties

        onIsAppReadyToUseChanged: {
            if(systemProperties.isAppReadyToUse) {
                printLog("[AppInterfaces] getLaunchPoints");
                interfaces.channels.init();
                interfaces.launchPoints.getLaunchPoints();
                interfaces.connections.initConnections();
                interfaces.account.getAccountData();
            }
        }

        onAccountDataUpdated: {
            console.log("[UiController] accountDataUpdated");
            interfaces.account.getAccountData();
        }

        onIsDeviceAuthenticatedChanged: {
            if (systemProperties.isDeviceAuthenticated) {
                interfaces.application.getSdpServiceItem(function (response) {
                    if (checkInitPopupHomeShown) {
                        root.checkInitPopup();
                    }
                });
            }
        }
    }

    onAppLaunched: {
        printLog("[agents] onAppLaunched");
        systemProperties.homePromotionData.push({"type" : "homeLaunchEndTime","time" : new Date()});

        if(systemProperties.showAdLaunchLoader) systemProperties.showAdLaunchLoader = false;

        if(interfaces.iot && interfaces.iot.mustDownloadAppRes) {
            interfaces.iot.getDeviceAppResVersion();
        }
        interfaces.channels.getChannelData(function(response){
            interfaces.channels.updateLastInputChannel();
            interfaces.connections.getConnections();
            interfaces.livetv.getChannelPreview();
            if (!systemProperties.isSportsAlarmSupported) {
                interfaces.sportsAlarm.getSportsAlarmPreview();
            }
            if(systemProperties.isWEE) {
                interfaces.advertisement.makeAdBanner();
            }
        });
    }

    state: "hidden"

    states: [
        State {
            name: "hidden"
        },
        State {
            name: "half"
        },
        State {
            name: "main"
        },
        State {
            name: "sub"
        },
        State {
            name: "editMenu"
            extend: "main"
        }
    ]
    Keys.forwardTo: root.isEditMode ? (mainView.editMenu) : null

    Keys.onReleased: {
        uiController.startNavigation = true;

        switch(event.key) {
        case webOS.Key_webOS_Recent:
            break;
        case webOS.Key_webOS_Back:
        case webOS.Key_webOS_Exit:
            printLog("[UiController] Keys.onReleased back/exit key: " + event.key);
            root.goBack();
            break;
        case webOS.Key_webOS_ScreenRemote:
            if(mainView.settingPopup.popupAnimationRunning) return;
            root.handledScreenRemoteKey();
            break;
        case Qt.Key_Menu:
        case Qt.Key_Super_L:
            root.goFull();
            break;

        case webOS.Key_webOS_Red:
            break;
        case webOS.Key_webOS_Green:
            break;
        case webOS.Key_webOS_Blue:
            break;
        case webOS.Key_webOS_Yellow:
            break;
        default:
            break;
        }
    }

    Keys.onPressed: {
        uiController.startNavigation = true;

        switch(event.key) {
        case webOS.Key_webOS_Exit:
            printLog("[UiController] Keys.onPressed exit key: " + event.key);
            root.cancelTimer();
            interfaces.application.closeApp(systemProperties.appId);
            break;
        default:
            break;
        }
    }

    onIntroRanChanged: {
        printLog("[INITIALIZE] start auto launch dismiss timer " + introRan + "  " + isAutoLaunch)
        if(introRan) {
            if(root.isAutoLaunch) {
                root.startDismissTimer();
            }
        }
    }

    onExtendTimer: {
        if(root.isAutoLaunch) {
            root.startDismissTimer();
        }
    }

    onDismissTimerExpired: {
        if(root.isAutoLaunch) {
            root.cancelTimer();
            interfaces.application.closeApp(systemProperties.appId);
            root.isAutoLaunch = false;
        }
    }

    onHomeShownChanged: {
        if(homeShown) {
            interfaces.application.closeApp("com.webos.app.miracast-overlay");
            interfaces.application.setPqSlowChange(true);
            systemProperties.homeShownType = root.isBootingHome ? "bootingHome" : "homeKey";
            uiController.userLogger.homeShown(systemProperties.foreGroundAppId, systemProperties.home_type, systemProperties.homeShownType);
            startEulaAppLaunch();
            cmpAppLaunch();
        } else {
            needToHomeTitleSpeak = true;
            interfaces.application.setPqSlowChange(false);
        }
    }
    onCheckInitPopupHomeShownChanged: {
        if (checkInitPopupHomeShown) {
            root.checkInitPopup();
        }
    }

    property var reservedLaunch

    Connections {
        target: root.mainView

        onHideTransitonFinished: {
            printLog("onHideTransitonFinished")
            if(reservedLaunch !== undefined) {
                reservedLaunch();
            }
            reservedLaunch = undefined;
        }

        onSetShelfListModel: {
            if(interfaces.application) {
                console.log("mainView onSetShelfListModel")
                interfaces.application.reset();
                interfaces.application.setModel(viewState);
            }
        }

        onClearShelfModel: {
            if(interfaces.application) {
                console.log("onResetShelves : shelfListModel clear")
                interfaces.application.clearShelfListModel();
            }
        }
    }

    Connections {

        target: interfaces.voice
        ignoreUnknownSignals: true

        onNeedContext: {
            selectables.length = 0;
            scrollShelfId = "";
            pushCount = 0;

            switch(uiController.state) {
            case "main":
                shelfReadyCount = 0;
                Object.keys(shelfListReadyObj).map(function(item) {
                    if(shelfListReadyObj[item]) {
                        shelfReadyCount++;
                    }
                });
                setVoiceControlContext();
                break;
            case "editMenu":
                setVoiceControlContextForEdit();
                break;

            }
        }

        onPerformAction: {
            switch(uiController.state) {
            case "main":
                //main.performVoiceControl(interfaces.voice.actionInfo);
                printLog("perform Action : "+JSON.stringify(interfaces.voice.actionInfo));
                performVoiceControl(interfaces.voice.actionInfo);
                break;
            case "editMenu":
                performVoiceControlForEdit(interfaces.voice.actionInfo);
                break;
            }
        }
    }

    function handledScreenRemoteKey() {
        if(isEditMode && mainView.editMenu && !mainView.settingPopup.visible) {
            if(root.editModeState === "shelfEditPage") {
                mainView.editMenu.shelfListEditPage.createSettingPopup();
            } else {
                mainView.editMenu.createSettingPopup();
            }
            return;
        }

        if(isEditMode && mainView.editMenu && mainView.settingPopup.visible) {
            mainView.editMenu.closeSettingPopup();
            return;
        }

        interfaces.application.goToScreenRemote();
    }

    function setWindowVisible(visible) {
        printLog("[LIFECYCLE] setWindowVisible: " + visible)

        if (visible) {
            rootWindow.showWindow();
        } else {
            rootWindow.hideWindow();
        }
        isHomeADLaunched = true;
    }

    function goBack() {
        switch(root.state) {
        case "half":
        case "main":
            root.cancelTimer();
            interfaces.application.closeApp(systemProperties.appId);
            break;
        }
    }

    function goFull() {
        switch(root.state) {
        case "half":
            root.goToState("main");
            break;
        case "main":
            root.closing();
            closeTimer.restart();
            break;
        }
    }

    Timer {

        id: closeTimer

        interval: 100

        onTriggered: {
            interfaces.application.closeApp(systemProperties.appId);
        }

    }

    function dismissApp(keepAlive) {
        printLog("[LIFECYCLE] dismissApp keepAlive: " + keepAlive);
        root.cancelTimer();
        if(root.isHiddenMode) {
            root.hideWindow();
        } else {
            root.goToState("hidden");
        }

        isHomeADLaunched = false;
    }

    function executeLaunch(mode, extraParam, isBootingHome) {
        if (root.wiiosTryRedirect(mode, extraParam, isBootingHome)) return;
        rootWindow.wiiosTrace("controller.executeLaunch", {
            mode: mode, bootArgument: isBootingHome,
            extraParamType: typeof extraParam
        });
        printLog(" root.executeLaunch " +  root.stateAboutToChange + "  " + mode + "  " + root.isHiddenMode + " tempMode : "+tempMode);
        if(isBootingHome !== undefined){
            root.isBootingHome = isBootingHome;
        }
        if(root.isHiddenMode) {

            interfaces.voice.register();

            switch(mode) {
            case "home":
            case "myapps":
                if(root.tempMode === "preload") {
                    root.tempMode = mode;
                    return;
                } else {
                    root.currentMode = "main";
                }
                break;
            case "preload":
                root.currentMode = "hidden";
                root.tempMode = root.currentMode;
                break;
            case "powerOn":
                if(root.tempMode === "preload") {
                    root.tempMode = mode;
                    return;
                } else {
                    root.isAutoLaunch = true;
                    root.currentMode = "main";
                }
                break;
            case "aiEdit":
                root.currentMode = "main";
                root.goToAiEdit();
                break;
            default :
                root.currentMode = "main";
                break;
            }
        } else {

            switch(mode) {
            case "preload":
                return;
            case "editMode":
                uiController.startEdit("appEditButton");
                return;
            case "deleteApp":
                root.removeLaunchPoint(extraParam);
                return;
            case "aiEdit":
                root.goToAiEdit();
                break;
            case "soundOut":
                root.currentMode = "main";
                interfaces.connections.bluetoothSurroundClicked();
                break;
            case "launchByInput":
                interfaces.connections.launchAppByASM(extraParam);
                break;
            case "launchByWeather":
                systemProperties.needWeatherCardLoading = true;
                systemProperties.isAllowLocationForWeatherInfo = true;
                interfaces.aiBoard.allowWeather();
                interfaces.aiBoard.setWeatherAllowSettingsService();
                interfaces.aiBoard.getWeatherInfo();
                break;
            case "powerOn":
                if(root.currentMode === "main") return;
                root.isAutoLaunch = true;
                root.currentMode = "main";
                break;
            default :
                root.cancelTimer();
                root.currentMode = "main";
                break;
            }
        }

        root.goToState(root.currentMode);
    }

    function goToState(state) {
        rootWindow.wiiosTrace("controller.goToState", {nextState: state});
        if(state ==="editMenu" && mainView.editMenuLoaderStatus !== Loader.Ready)
            return;

        if(root.isHiddenMode && state !== "hidden") {
            appLaunched();
        }

        if(state !== "half")root.cancelTimer();

        root.currentMode = state;
        root.stateAboutToChange = state;
        root.state = state;
        console.log(" root.stateAboutToChange " +  root.stateAboutToChange)
    }

    function checkInitPopup() {
        if (systemProperties.country === "DEU") {
            if (systemProperties.enableHomeLegalPopup && systemProperties.supportAvmsd) {
                if(utils.checkUrlExists(mainView.popupFileUrl)){
                    initPopUpTimer.start();
                }
            }
        }
    }

    Timer {
        id: initPopUpTimer
        interval: 2 * 1000
        property var retryCount: 0
        onTriggered: {
            if(rootWindow.active){
                systemProperties.notiLegalPopup = true;
                systemProperties.notiLegalPopup = false;
                interfaces.application.setLegalSettingService(true);
                retryCount = 0;
            } else {
                if(retryCount < 3) {
                    retryCount++;
                    initPopUpTimer.start();
                } else {
                    retryCount = 0;
                }
            }
        }
    }

    function goToEdit() {
        goToState("editMenu");
    }

    function goToAiEdit() {
        if(/*root.homeShown*/1) {
            root.voiceEdit = true;
            if(!root.isHiddenMode) {
                if(root.isEditMode) {
                    if (mainView.editMenu) {
                        mainView.editMenu.runVoiceEdit();
                    }
                } else {
                    mainView.startEdit("app");
                    goToState("editMenu");
                }
            }
        } else {
            dismissApp();
        }
    }

    function editMainAvailable() {
        var param = {
            "iconUrl": "",
            "message": stringSheet.home_188,
            "noaction": true};

        if(systemProperties.miracastTxPlaying) {
            interfaces.application.createToast(param);
        }

        return !systemProperties.miracastTxPlaying
    }

    function startEdit(startPoint) {
        if(root.editMainAvailable()) {
            mainView.startEdit(startPoint);
        }
    }

    function setEditModeState(s) {
        root.editModeState = s;
    }

    function removeLaunchPoint(param) {
        interfaces.launchPoints.removeLaunchPoint(param);
    }

    function startEulaAppLaunch() {
        printLog("[LIFECYCLE] homeLaunchByHomeKey : " + homeLaunchByHomeKey + ", isLaunchEulaByHome : " + systemProperties.isLaunchEulaByHome);
        if (homeLaunchByHomeKey && systemProperties.isLaunchEulaByHome) {
            interfaces.application.setLaunchEulaByHome(false);
            interfaces.application.launchApp("com.webos.app.eula", "", {"appId": "com.webos.app.home", "target": "eula", "context": "eulaUpdate"});
        }
    }

    function cmpAppLaunch() {
        printLog("[LIFECYCLE] homeShownType : " + systemProperties.homeShownType + ", networkConnected : " + systemProperties.networkConnected + ", isLaunchEulaByHome : " + systemProperties.isLaunchEulaByHome);
        if (systemProperties.homeShownType !== "" &&
            systemProperties.homeShownType !== "bootingHome" &&
            systemProperties.networkConnected &&
            !systemProperties.isLaunchEulaByHome) {
            interfaces.promotion.launchCMPApp();
        }
    }

    Connections {
        target: rootWindow
        onFivewayKeyEvent: {
            root.cancelTimer();
        }
        onActiveChanged: {
            if(active){
                checkInitPopup();
            }
        }
    }

    function cancelTimer() {
        dismissTimer.stop();
        root.isAutoLaunch = false;
    }

    function startDismissTimer() {
        printLog("[LIFECYCLE] startDismissTimer")
        dismissTimer.restart();
    }

    Timer {

        id: dismissTimer

        interval: 8000

        onTriggered: {
            root.dismissTimerExpired();
        }
    }

    /*For debugging*/
    //User logger
    UserLogger {
        id: userLogger
        objectName: "userLogger"
    }

    //Onscreen logger
    OnScreenLog {

        id: log

        z: 10000
        anchors.right: parent.right
        isAppActive: rootWindow.active

        Connections {
            target: rootWindow
            onPrintLog: {
                log.printLog(value)
            }

            onPrintLS: {
                log.printLS(value)
            }
        }
    }
}
