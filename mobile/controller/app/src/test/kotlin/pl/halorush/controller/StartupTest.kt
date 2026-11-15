package pl.halorush.controller

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.Context
import android.content.pm.PackageManager
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import com.neurotec.brainaccess.transport.NordicTransport
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.annotation.LooperMode

/** A BLE implementation which refuses initialization must not prevent opening the app. */
@Implements(value = NordicTransport::class, isInAndroidSdk = false)
class FailingTransport {
    @Implementation fun __constructor__(context: Context) {
        throw SecurityException("Test: Bluetooth initialization denied")
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [31, 35, 36], shadows = [FailingTransport::class])
@LooperMode(LooperMode.Mode.PAUSED)
class StartupTest {
    private fun views(view: View): List<View> = listOf(view) + if (view is ViewGroup)
        (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    @Test fun `fresh install opens configuration before touching Bluetooth`() {
        val app = RuntimeEnvironment.getApplication()
        shadowOf(app).denyPermissions(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        val owner = Robolectric.buildActivity(MainActivity::class.java).setup()
        try {
            shadowOf(Looper.getMainLooper()).idle()
            assertTrue(views(owner.get().window.decorView).filterIsInstance<Button>().any { it.text == "Dalej" })
            assertNull(shadowOf(owner.get()).lastRequestedPermission)
        } finally { owner.pause().stop().destroy() }
    }

    @Test fun `HALO asks for permission before initializing SDK and displays initialization failure`() {
        val app = RuntimeEnvironment.getApplication()
        shadowOf(app).denyPermissions(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        val owner = Robolectric.buildActivity(MainActivity::class.java).setup()
        val activity = owner.get()
        fun all() = views(activity.window.decorView)
        fun click(label: String) = all().filterIsInstance<Button>().first { it.text.toString() == label }.performClick()
        try {
            all().filterIsInstance<EditText>().first().setText("ws://127.0.0.1:8766/ws/controller")
            click("Dalej")
            click("Szukaj HALO")
            assertEquals(setOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT),
                shadowOf(activity).lastRequestedPermission.requestedPermissions.toSet())
            shadowOf(app).grantPermissions(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
            shadowOf(app.packageManager).setSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE, true)
            @Suppress("DEPRECATION")
            shadowOf(BluetoothAdapter.getDefaultAdapter()).setEnabled(true)
            click("Szukaj HALO")
            shadowOf(Looper.getMainLooper()).idle()
            assertTrue(all().filterIsInstance<TextView>().any { it.text.contains("Test: Bluetooth initialization denied") })
            assertTrue(all().filterIsInstance<Button>().any { it.text == "Szukaj HALO" })
        } finally { owner.pause().stop().destroy() }
    }
}
