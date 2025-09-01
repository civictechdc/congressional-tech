import { DashboardContent } from "@/components/dashboard/dashboard-content";

export default function DashboardPage() {
    return (
        <main className="flex min-h-screen flex-col items-center justify-center bg-gray-50">
            <h1 className="text-3xl font-bold text-gray-900">
                House Congressional YouTube EventID Linkage Tracker
            </h1>
            <DashboardContent />
        </main>
    );
}
