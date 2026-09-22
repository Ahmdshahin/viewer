export default function Dashboard() {
  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold text-slate-800 mb-6">Dashboard</h1>
      <div className="grid grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded shadow border-t-4 border-blue-500">
          <h2 className="text-gray-500 text-sm uppercase tracking-wider">Land Parcels</h2>
          <p className="text-4xl font-bold mt-2 text-slate-800">152</p>
        </div>
        <div className="bg-white p-6 rounded shadow border-t-4 border-orange-500">
          <h2 className="text-gray-500 text-sm uppercase tracking-wider">Occupations (Eshghalat)</h2>
          <p className="text-4xl font-bold mt-2 text-slate-800">71</p>
        </div>
        <div className="bg-white p-6 rounded shadow border-t-4 border-green-500">
          <h2 className="text-gray-500 text-sm uppercase tracking-wider">Survey Points</h2>
          <p className="text-4xl font-bold mt-2 text-slate-800">973</p>
        </div>
      </div>
      
      <div className="mt-8 bg-white p-6 rounded shadow">
        <h2 className="text-xl font-bold mb-4">Welcome to GeoPortal</h2>
        <p className="text-gray-600">
          Use the Map Viewer to interact with the spatial database, identify features, 
          and check for overlaps. Editors can upload new Shapefile datasets via the upload tools.
        </p>
      </div>
    </div>
  );
}
