package com.bnb.office;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Calendar;

/**
 * Local task reminders: 14 days, 7 days and 1 day before each task's due date, at 9:00 AM.
 * The web app hands over the open tasks (id, title, client, due) each time it is opened;
 * alarms are stored on the phone, so they fire even when the app is closed.
 */
public class Reminders extends BroadcastReceiver {
    static final String PREFS = "bnb_reminders";
    static final String KEY_TASKS = "tasks";
    static final String KEY_CODES = "codes";
    static final String CHANNEL = "bnb_tasks";
    static final int[] OFFSETS = {14, 7, 1};
    static final int HOUR = 9;

    /** Called by the web app with a JSON array of {id,title,client,due:"YYYY-MM-DD"}. */
    static void save(Context ctx, String json) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TASKS, json == null ? "[]" : json).apply();
        schedule(ctx);
    }

    static void schedule(Context ctx) {
        try {
            SharedPreferences sp = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
            if (am == null) return;

            // cancel what was scheduled before
            JSONArray old = new JSONArray(sp.getString(KEY_CODES, "[]"));
            for (int i = 0; i < old.length(); i++) {
                PendingIntent pi = PendingIntent.getBroadcast(ctx, old.getInt(i), new Intent(ctx, Reminders.class), flags());
                am.cancel(pi);
            }

            JSONArray tasks = new JSONArray(sp.getString(KEY_TASKS, "[]"));
            JSONArray codes = new JSONArray();
            long now = System.currentTimeMillis();
            for (int i = 0; i < tasks.length(); i++) {
                JSONObject t = tasks.getJSONObject(i);
                String id = t.optString("id"), due = t.optString("due");
                String[] p = due.split("-");
                if (id.isEmpty() || p.length != 3) continue;
                for (int off : OFFSETS) {
                    Calendar c = Calendar.getInstance();
                    c.clear();
                    c.set(Integer.parseInt(p[0]), Integer.parseInt(p[1]) - 1, Integer.parseInt(p[2]), HOUR, 0, 0);
                    c.add(Calendar.DAY_OF_MONTH, -off);
                    long at = c.getTimeInMillis();
                    if (at <= now) continue;
                    int code = (id + "|" + off).hashCode();
                    Intent in = new Intent(ctx, Reminders.class);
                    in.setAction("com.bnb.office.REMIND");
                    in.putExtra("code", code);
                    in.putExtra("title", t.optString("title"));
                    in.putExtra("client", t.optString("client"));
                    in.putExtra("due", due);
                    in.putExtra("off", off);
                    PendingIntent pi = PendingIntent.getBroadcast(ctx, code, in, flags());
                    if (Build.VERSION.SDK_INT >= 23) am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
                    else am.set(AlarmManager.RTC_WAKEUP, at, pi);
                    codes.put(code);
                }
            }
            sp.edit().putString(KEY_CODES, codes.toString()).apply();
        } catch (Exception ignored) {
        }
    }

    private static int flags() {
        return PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
    }

    @Override
    public void onReceive(Context ctx, Intent in) {
        String action = in.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(action) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            schedule(ctx); // alarms are lost on reboot, so put them back
            return;
        }
        try {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationChannel ch = new NotificationChannel(CHANNEL, "تذكير التسكات", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("تذكير قبل ميعاد التسك بأسبوعين وأسبوع ويوم");
                nm.createNotificationChannel(ch);
            }
            int off = in.getIntExtra("off", 1);
            String when = off == 1 ? "بكرة آخر ميعاد" : off == 7 ? "فاضل أسبوع" : "فاضل أسبوعين";
            String title = in.getStringExtra("title"), client = in.getStringExtra("client"), due = in.getStringExtra("due");
            String head = when + ": " + (title == null ? "تسك" : title);
            String body = (client == null || client.isEmpty() ? "" : client + " — ") + "الميعاد " + dmy(due);

            Intent open = new Intent(ctx, MainActivity.class);
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            int code = in.getIntExtra("code", 0);
            PendingIntent tap = PendingIntent.getActivity(ctx, code, open, flags());

            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(ctx, CHANNEL) : new Notification.Builder(ctx);
            b.setSmallIcon(android.R.drawable.ic_popup_reminder)
                    .setContentTitle(head)
                    .setContentText(body)
                    .setStyle(new Notification.BigTextStyle().bigText(body))
                    .setAutoCancel(true)
                    .setContentIntent(tap);
            if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_HIGH);
            nm.notify(code, b.build());
        } catch (Exception ignored) {
        }
    }

    private static String dmy(String iso) {
        if (iso == null) return "";
        String[] p = iso.split("-");
        return p.length == 3 ? p[2] + "/" + p[1] + "/" + p[0] : iso;
    }
}
