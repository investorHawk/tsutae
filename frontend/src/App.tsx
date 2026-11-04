import { Navigate, Route, Routes } from "react-router-dom";
import RequireDoctor from "./auth/RequireDoctor";
import DoctorLayout from "./layouts/DoctorLayout";
import DoctorShell from "./layouts/DoctorShell";
import PatientLayout from "./layouts/PatientLayout";
import Login from "./pages/doctor/Login";
import PatientDetail from "./pages/doctor/PatientDetail";
import Patients from "./pages/doctor/Patients";
import Pipeline from "./pages/doctor/Pipeline";
import Settings from "./pages/doctor/Settings";
import Unprocessed from "./pages/doctor/Unprocessed";
import Visits from "./pages/doctor/Visits";
import History from "./pages/patient/History";
import Register from "./pages/patient/Register";
import Today from "./pages/patient/Today";
import Visit from "./pages/patient/Visit";

/**
 * 全ルート（docs/architecture.md §9）。Router は main.tsx の BrowserRouter
 * （テストでは MemoryRouter）。
 */
export default function App() {
  return (
    <Routes>
      <Route element={<PatientLayout />}>
        <Route path="/register" element={<Register />} />
        <Route path="/today" element={<Today />} />
        <Route path="/history" element={<History />} />
        <Route path="/visit" element={<Visit />} />
      </Route>

      <Route path="/doctor" element={<DoctorLayout />}>
        <Route path="login" element={<Login />} />
        <Route element={<RequireDoctor />}>
          <Route element={<DoctorShell />}>
            <Route index element={<Visits />} />
            <Route path="patients" element={<Patients />} />
            <Route path="patients/:pid" element={<PatientDetail />} />
            <Route path="settings" element={<Settings />} />
            <Route path="pipeline/:visitId" element={<Pipeline />} />
            <Route path="unprocessed/:visitId" element={<Unprocessed />} />
            <Route path="*" element={<Navigate to="/doctor" replace />} />
          </Route>
        </Route>
      </Route>

      <Route path="/" element={<Navigate to="/today" replace />} />
      <Route path="*" element={<Navigate to="/today" replace />} />
    </Routes>
  );
}
