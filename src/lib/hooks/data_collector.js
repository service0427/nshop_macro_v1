/* 
   Total Data Spy (Open Detection Mode)
   - Exposes every possible identifier for UI state analysis.
*/

console.log("[*] Total Data Spy Active - Exposing all anchors");

var last_text = "";
var last_desc = "";

Java.perform(function() {
    // 1. [WINDOW] 다이얼로그 및 팝업 감지
    var Dialog = Java.use("android.app.Dialog");
    Dialog.show.implementation = function() {
        console.log("[WINDOW_UI] Dialog/Popup Appearance: " + this.getClass().getName());
        this.show();
    };

    // 2. [DESC] 접근성 설명(Content Description) 감지
    // Compose 배너의 "닫기 버튼" 같은 정보가 여기서 나옵니다.
    var View = Java.use("android.view.View");
    View.setContentDescription.implementation = function(contentDescription) {
        if (contentDescription) {
            var d = contentDescription.toString();
            if (d !== last_desc) {
                console.log("[DESC_UI] Description Set: " + d);
                last_desc = d;
            }
        }
        this.setContentDescription(contentDescription);
    };

    // 3. [CLICKABLE] 클릭 가능한 요소가 화면에 나타날 때 감지
    View.setOnClickListener.implementation = function(listener) {
        if (listener) {
            var resId = "none";
            try { resId = this.getContext().getResources().getResourceEntryName(this.getId()); } catch(e) {}
            // console.log("[ATTACH_UI] Clickable Element: " + resId);
        }
        return this.setOnClickListener(listener);
    };

    // 4. [TEXT] 모든 네이티브 텍스트 출력 감지
    var TextView = Java.use("android.widget.TextView");
    TextView.setText.overload('java.lang.CharSequence').implementation = function(text) {
        if (text) {
            var str = text.toString();
            if (str.length > 0 && str !== last_text) {
                console.log("[TEXT_UI] Value: " + str);
                last_text = str;
            }
        }
        return this.setText(text);
    };

    // 5. [PAGE] 페이지 전환 감지
    var Activity = Java.use("android.app.Activity");
    Activity.onResume.implementation = function() {
        console.log("[PAGE_UI] Activity Focus: " + this.getClass().getName());
        this.onResume();
    };
});
