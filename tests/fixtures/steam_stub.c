#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#ifdef _WIN32
#define API __declspec(dllexport)
#pragma pack(push, 8)
#else
#define API __attribute__((visibility("default")))
#pragma pack(push, 4)
#endif
typedef struct { int32_t result; bool legal; uint64_t item; } UpdateResult;
#pragma pack(pop)

static int mode, shutdowns, submits, callbacks;
static uint32_t app;
static uint64_t item;
static char content[4096], notes[65537];
API void test_reset(int value) { mode=value; shutdowns=submits=callbacks=0; app=0; item=0; content[0]=notes[0]=0; }
API int test_shutdowns(void) { return shutdowns; }
API int test_submits(void) { return submits; }
API uint32_t test_app(void) { return app; }
API uint64_t test_item(void) { return item; }
API const char *test_content(void) { return content; }
API const char *test_notes(void) { return notes; }
API bool SteamAPI_IsSteamRunning(void) { return mode!=1; }
API int SteamAPI_InitFlat(char *error) { strcpy(error,"private-native-error-canary"); return mode==3 ? 2 : 0; }
API void SteamAPI_Shutdown(void) { shutdowns++; }
API void *SteamAPI_SteamUser_v023(void) { return (void *)(uintptr_t)1; }
API void *SteamAPI_SteamUtils_v010(void) { return (void *)(uintptr_t)2; }
API void *SteamAPI_SteamUGC_v021(void) { return (void *)(uintptr_t)3; }
API bool SteamAPI_ISteamUser_BLoggedOn(void *self) { (void)self; return mode!=2 && !(mode==11 && callbacks>0); }
API uint32_t SteamAPI_ISteamUtils_GetAppID(void *self) { (void)self; return mode==4 ? 441 : 440; }
API uint64_t SteamAPI_ISteamUGC_StartItemUpdate(void *self,uint32_t app_id,uint64_t item_id) {
    (void)self; app=app_id; item=item_id; return UINT64_C(9876543212345);
}
API bool SteamAPI_ISteamUGC_SetItemContent(void *self,uint64_t handle,const char *value) {
    (void)self; (void)handle; strncpy(content,value,sizeof(content)-1); return mode!=12;
}
API uint64_t SteamAPI_ISteamUGC_SubmitItemUpdate(void *self,uint64_t handle,const char *value) {
    (void)self; (void)handle; submits++; strncpy(notes,value,sizeof(notes)-1); return mode==5 ? 0 : UINT64_C(9876543212346);
}
API void SteamAPI_RunCallbacks(void) { callbacks++; }
API bool SteamAPI_ISteamUtils_IsAPICallCompleted(void *self,uint64_t call,bool *failed) {
    (void)self; (void)call; *failed=false; return mode!=10 && mode!=11;
}
API bool SteamAPI_ISteamUtils_GetAPICallResult(void *self,uint64_t call,void *buffer,int size,int expected,bool *failed) {
    (void)self; (void)call;
    if (expected!=3404 || size!=(int)sizeof(UpdateResult)) return false;
    UpdateResult *result=(UpdateResult *)buffer;
    *failed=mode==6;
    result->result=mode==7 ? 15 : 1; result->legal=mode==9; result->item=mode==8 ? item+1 : item;
    return true;
}
