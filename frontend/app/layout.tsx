import "./globals.css"; import type { Metadata } from "next";
export const metadata: Metadata={title:"Fraud Investigation Workbench",description:"Grounded fraud investigation review"};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
