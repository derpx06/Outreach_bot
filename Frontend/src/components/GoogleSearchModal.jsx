import React from 'react';
import { X, ExternalLink, Search } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export function GoogleSearchModal({ isOpen, onClose, query }) {
    const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}&igu=1`;

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        key="backdrop"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[60]"
                        onClick={onClose}
                    />

                    {/* Sidebar Content */}
                    <motion.div
                        key="sidebar"
                        initial={{ x: "100%", opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: "100%", opacity: 0 }}
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        className="fixed inset-y-0 right-0 z-[61] w-full sm:w-[500px] bg-[#0A0A0A] border-l border-white/5 shadow-2xl flex flex-col"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-[#0A0A0A]">
                            <div className="flex items-center gap-2 text-zinc-200">
                                <Search className="w-4 h-4 text-blue-400" />
                                <span className="font-medium truncate max-w-[250px]">Search: {query}</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <a
                                    href={searchUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="p-2 hover:bg-white/10 rounded-lg text-zinc-400 hover:text-white transition-colors"
                                    title="Open in new tab"
                                >
                                    <ExternalLink className="w-4 h-4" />
                                </a>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-white/10 rounded-lg text-zinc-400 hover:text-white transition-colors"
                                >
                                    <X className="w-5 h-5" />
                                </button>
                            </div>
                        </div>

                        {/* Content */}
                        <div className="flex-1 bg-white relative">
                            <iframe
                                src={searchUrl}
                                className="w-full h-full border-0"
                                title="Google Search"
                                sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
                            />

                            {/* Overlay hint if iframe fails to load */}
                            <div className="absolute top-0 left-0 right-0 p-2 bg-yellow-500/10 text-yellow-600 text-xs text-center border-b border-yellow-500/20 pointer-events-none">
                                If content looks blocked, use the 'Open in new tab' icon above.
                            </div>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
