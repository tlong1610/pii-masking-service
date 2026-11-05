// Chạy một lần khi volume còn trống. Luồng quét và xuất chỉ dùng user này, không có quyền ghi.
const dbName = process.env.MOCKUP_MONGO_DB;

db.getSiblingDB("admin").createUser({
  user: process.env.MOCKUP_MONGO_READONLY_USER,
  pwd: process.env.MOCKUP_MONGO_READONLY_PASSWORD,
  roles: [
    { role: "read", db: dbName },
    { role: "read", db: `${dbName}_perf` },
  ],
});
