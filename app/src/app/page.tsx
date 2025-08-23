export default function Home() {
    return (
        <main className="flex min-h-screen flex-1 flex-col items-center justify-center bg-gray-50">
            <img
                src="/congress-1800w.png"
                alt="Header Image"
                className="z-0 h-full max-h-screen w-auto flex-1 object-cover"
            />
            <div className="relative z-10 max-w-2xl p-8 text-gray-900">
                <p>
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed dignissim, nisl sit
                    amet luctus suscipit, arcu orci venenatis nisl, eget facilisis magna tellus sed
                    justo.
                </p>
                <p>
                    Praesent pharetra magna et velit hendrerit, a ultrices sem faucibus. Nullam at
                    consectetur nulla, a efficitur libero. Sed sodales lectus vel eros accumsan, at
                    malesuada risus iaculis.
                </p>
                <p>
                    Morbi porttitor, nulla in fermentum tincidunt, est neque tempor est, id aliquet
                    odio libero sed arcu. Duis vel est sed arcu tincidunt viverra sit amet nec
                    metus.
                </p>
                <p>
                    Proin id dolor non turpis euismod fermentum. Aliquam erat volutpat. Aenean nec
                    leo sit amet ligula congue facilisis in ac erat.
                </p>
                <p>
                    Quisque sed erat eget orci tristique viverra nec vitae risus. Suspendisse a
                    metus in nunc tempor vestibulum sed nec sapien.
                </p>
            </div>
        </main>
    );
}
